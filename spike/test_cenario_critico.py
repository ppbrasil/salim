"""Protótipo DESCARTÁVEL: prova que o modelo de docs/modelo.sql aguenta o cenário crítico.

Cenário (hoje = 2026-11-19):
  fatura de cartão com compras em 2 competências (jun e jul) -> parcelada em 5x com juros
  -> parcela 1 paga em dia -> parcelas 2 e 3 atrasam -> renegociadas em 1 título novo (+ multa)
  -> liquidado em 30/11. As competências originais não podem mudar em nenhum momento.
"""
import sqlite3
from collections import defaultdict
from fractions import Fraction
from pathlib import Path

import pytest

DDL = (Path(__file__).parent.parent / "src" / "salim" / "schema.sql").read_text()


class Book:
    def __init__(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.executescript(DDL)
        self.acc: dict[str, int] = {}
        self.txdate: dict[int, str] = {}
        self.obl: dict[str, int] = {}
        self.txs: list[int] = []

    def account(self, code, name, type, **flags):
        cols = ["code", "name", "type", *flags]
        vals = [code, name, type, *flags.values()]
        q = f"INSERT INTO accounts ({','.join(cols)}) VALUES ({','.join('?' * len(vals))})"
        self.acc[code] = self.db.execute(q, vals).lastrowid

    def tx(self, date, desc, kind="general"):
        i = self.db.execute("INSERT INTO transactions (event_date, description, kind) VALUES (?,?,?)",
                            (date, desc, kind)).lastrowid
        self.txdate[i] = date
        self.txs.append(i)
        return i

    def new_obl(self, key, acct, txid, kind, due, **kw):
        cols = ["account_id", "kind", "due_date", "created_by_tx_id", *kw]
        vals = [self.acc[acct], kind, due, txid, *kw.values()]
        q = f"INSERT INTO obligations ({','.join(cols)}) VALUES ({','.join('?' * len(vals))})"
        self.obl[key] = self.db.execute(q, vals).lastrowid

    def post(self, txid, acct, cents, comp=None, obl=None):
        comp = comp or self.txdate[txid][:7] + "-01"
        self.db.execute(
            "INSERT INTO postings (transaction_id, account_id, amount_cents, competence_month, obligation_id)"
            " VALUES (?,?,?,?,?)",
            (txid, self.acc[acct], cents, comp, self.obl[obl] if obl else None))

    def q(self, sql, **params):
        return self.db.execute(sql, params).fetchall()


# ---------------------------------------------------------------- cenário em fases
def base():
    b = Book()
    b.account("1.01.01", "Banco", "asset", is_cash=1)
    b.account("2.01.01", "Cartão Nubank", "liability", tracks_obligations=1, closing_day=25, due_day=5)
    b.account("2.02.01", "Parcelamentos e Renegociações", "liability", tracks_obligations=1)
    b.account("5.02.01", "Supermercado", "expense")
    b.account("5.02.02", "Restaurantes", "expense")
    b.account("5.05.01", "Assinaturas", "expense")
    b.account("5.07.01", "Juros", "expense")
    b.account("5.07.02", "Multas", "expense")
    b.account("5.01.01", "Aluguel", "expense")
    b.account("5.01.03", "Luz", "expense")
    b.account("5.08.01", "Eletrônicos", "expense")
    b.account("2.02.02", "Contas a Pagar", "liability", tracks_obligations=1)
    b.account("1.03.01", "Reembolsos a Receber", "asset", tracks_obligations=1, is_temporary=1)
    return b


def compras_na_fatura(b):
    t1 = b.tx("2026-06-28", "Mercado", "purchase")
    b.new_obl("INV", "2.01.01", t1, "invoice", "2026-08-05", reference="2026-07", closing_date="2026-07-25")
    b.post(t1, "5.02.01", 60000, comp="2026-06-01"); b.post(t1, "2.01.01", -60000, obl="INV")
    t2 = b.tx("2026-07-10", "Restaurante", "purchase")
    b.post(t2, "5.02.02", 40000); b.post(t2, "2.01.01", -40000, obl="INV")
    t3 = b.tx("2026-07-20", "Assinatura", "purchase")
    b.post(t3, "5.05.01", 10000); b.post(t3, "2.01.01", -10000, obl="INV")


def parcelar_fatura(b):
    t = b.tx("2026-08-04", "Parcelamento da fatura 2026-07 em 5x", "consolidation")
    b.post(t, "2.01.01", 110000, obl="INV")           # liquida a fatura
    b.post(t, "5.07.01", 10000)                       # juros do parcelamento (linha própria)
    due = ["2026-09-05", "2026-10-05", "2026-11-05", "2026-12-05", "2027-01-05"]
    for n, d in enumerate(due, 1):
        b.new_obl(f"P{n}", "2.02.01", t, "installment", d, reference=f"parc {n}/5",
                  installment_no=n, installment_total=5)
        b.post(t, "2.02.01", -24000, obl=f"P{n}")


def pagar_p1(b):
    t = b.tx("2026-09-05", "Pagamento parcela 1/5", "payment")
    b.post(t, "2.02.01", 24000, obl="P1"); b.post(t, "1.01.01", -24000)


def renegociar_p2_p3(b):
    t = b.tx("2026-11-19", "Renegociação das parcelas 2 e 3", "consolidation")
    b.new_obl("N", "2.02.01", t, "consolidated", "2026-11-30", reference="reneg 2+3")
    b.post(t, "2.02.01", 24000, obl="P2"); b.post(t, "2.02.01", 24000, obl="P3")
    b.post(t, "5.07.02", 3000)                        # multa, em linha própria
    b.post(t, "2.02.01", -51000, obl="N")


def liquidar_n(b):
    t = b.tx("2026-11-30", "Pagamento da renegociação", "payment")
    b.post(t, "2.02.01", 51000, obl="N"); b.post(t, "1.01.01", -51000)


# ---------------------------------------------------------------- consultas
def status(b, today):
    rows = b.q("""
      SELECT o.reference ref, v.balance_cents bal,
        CASE WHEN v.balance_cents = 0 THEN 'quitada'
             WHEN v.balance_cents < 0 THEN 'credito'
             WHEN o.kind = 'invoice' AND o.closing_date >= :today THEN 'aberta'
             WHEN o.due_date < :today THEN 'atrasada'
             ELSE 'a_vencer' END st,
        CASE WHEN v.balance_cents > 0 AND o.due_date < :today
             THEN CAST(julianday(:today) - julianday(o.due_date) AS INT) ELSE 0 END days_late
      FROM obligations o JOIN v_obligation_balance v ON v.obligation_id = o.id""", today=today)
    return {r["ref"]: (r["st"], r["bal"], r["days_late"]) for r in rows}


def dre_por_mes(b):
    out = defaultdict(int)
    for r in b.q("SELECT month, SUM(amount_cents) c FROM v_dre GROUP BY month"):
        out[r["month"]] = r["c"]
    return dict(out)


def composicao(b, obl_id) -> dict:
    """De quais despesas é feito este título? Segue a linhagem pelos lançamentos que o criaram."""
    out = defaultdict(Fraction)
    for row in b.q("SELECT DISTINCT transaction_id t FROM postings WHERE obligation_id=:o AND amount_cents<0", o=obl_id):
        t = row["t"]
        meu = -b.q("SELECT SUM(amount_cents) s FROM postings WHERE transaction_id=:t AND obligation_id=:o"
                   " AND amount_cents<0", t=t, o=obl_id)[0]["s"]
        total_cred = -b.q("SELECT SUM(amount_cents) s FROM postings WHERE transaction_id=:t AND amount_cents<0", t=t)[0]["s"]
        share = Fraction(meu, total_cred)
        for leg in b.q("SELECT p.amount_cents c, p.obligation_id o, a.code FROM postings p"
                       " JOIN accounts a ON a.id=p.account_id WHERE p.transaction_id=:t AND p.amount_cents>0", t=t):
            if leg["o"]:
                orig = -b.q("SELECT SUM(amount_cents) s FROM postings WHERE obligation_id=:o AND amount_cents<0",
                            o=leg["o"])[0]["s"]
                for k, v in composicao(b, leg["o"]).items():
                    out[k] += v * Fraction(leg["c"], orig) * share
            else:
                out[leg["code"]] += leg["c"] * share
    return dict(out)


# ---------------------------------------------------------------- testes
def test_invariante_global_e_por_lancamento():
    b = base(); compras_na_fatura(b); parcelar_fatura(b); pagar_p1(b); renegociar_p2_p3(b); liquidar_n(b)
    assert b.q("SELECT SUM(amount_cents) s FROM postings")[0]["s"] == 0
    for t in b.txs:
        assert b.q("SELECT SUM(amount_cents) s FROM postings WHERE transaction_id=:t", t=t)[0]["s"] == 0


def test_fatura_com_varias_competencias_e_ciclo_de_vida():
    b = base(); compras_na_fatura(b)
    assert status(b, "2026-07-20")["2026-07"] == ("aberta", 110000, 0)      # ainda recebe compras
    assert status(b, "2026-07-26")["2026-07"] == ("a_vencer", 110000, 0)    # fechada, não venceu
    assert status(b, "2026-08-06")["2026-07"] == ("atrasada", 110000, 1)    # venceu sem pagar
    # competência ≠ mês da fatura: mercado de junho está na fatura de julho
    assert dre_por_mes(b) == {"2026-06-01": 60000, "2026-07-01": 50000}


def test_parcelamento_quita_fatura_e_cria_cronograma():
    b = base(); compras_na_fatura(b); parcelar_fatura(b)
    s = status(b, "2026-08-04")
    assert s["2026-07"][:2] == ("quitada", 0)
    assert [s[f"parc {n}/5"][1] for n in range(1, 6)] == [24000] * 5
    assert dre_por_mes(b)["2026-08-01"] == 10000                              # juros na competência do parcelamento
    assert dre_por_mes(b)["2026-06-01"] == 60000                              # competências originais intactas


def test_aging_antes_da_renegociacao():
    b = base(); compras_na_fatura(b); parcelar_fatura(b); pagar_p1(b)
    s = status(b, "2026-11-18")
    assert s["parc 1/5"][0] == "quitada"
    assert s["parc 2/5"] == ("atrasada", 24000, 44)
    assert s["parc 3/5"] == ("atrasada", 24000, 13)
    assert s["parc 4/5"][0] == "a_vencer" and s["parc 5/5"][0] == "a_vencer"


def test_renegociacao_nao_mexe_nas_competencias_originais():
    b = base(); compras_na_fatura(b); parcelar_fatura(b); pagar_p1(b)
    antes = dre_por_mes(b)
    renegociar_p2_p3(b)
    depois = dre_por_mes(b)
    assert {m: v for m, v in depois.items() if m != "2026-11-01"} == antes     # só nov ganhou algo
    assert depois["2026-11-01"] == 3000                                        # multa na competência da renegociação
    s = status(b, "2026-11-19")
    assert s["parc 2/5"][:2] == ("quitada", 0) and s["parc 3/5"][:2] == ("quitada", 0)
    assert s["reneg 2+3"] == ("a_vencer", 51000, 0)


def test_fluxo_de_caixa_executado_e_futuro():
    b = base(); compras_na_fatura(b); parcelar_fatura(b); pagar_p1(b); renegociar_p2_p3(b); liquidar_n(b)
    exec_ = {r["month"]: r["net_cents"] for r in b.q("SELECT * FROM v_cash_executed")}
    assert exec_ == {"2026-09": -24000, "2026-11": -51000}                     # caixa só quando saiu dinheiro
    fut = {r["expected_date"]: r["expected_cents"] for r in b.q("SELECT * FROM v_cash_future")}
    assert fut == {"2026-12-05": -24000, "2027-01-05": -24000}
    # data planejada move a projeção sem mexer no vencimento
    b.db.execute("UPDATE obligations SET planned_date='2027-01-20' WHERE id=?", (b.obl["P4"],))
    fut = {r["expected_date"]: r["expected_cents"] for r in b.q("SELECT * FROM v_cash_future")}
    assert "2026-12-05" not in fut and fut["2027-01-20"] == -24000
    assert b.q("SELECT due_date d FROM obligations WHERE id=:o", o=b.obl["P4"])[0]["d"] == "2026-12-05"


def test_saldo_da_conta_e_a_soma_dos_titulos():
    b = base(); compras_na_fatura(b); parcelar_fatura(b); pagar_p1(b); renegociar_p2_p3(b)
    for code in ("2.01.01", "2.02.01"):
        conta = -b.q("SELECT COALESCE(SUM(amount_cents),0) s FROM postings WHERE account_id=:a", a=b.acc[code])[0]["s"]
        titulos = b.q("SELECT COALESCE(SUM(balance_cents),0) s FROM v_obligation_balance WHERE account_id=:a",
                      a=b.acc[code])[0]["s"]
        assert conta == titulos


def test_origem_rastreavel_da_divida_renegociada_ate_as_compras():
    b = base(); compras_na_fatura(b); parcelar_fatura(b); pagar_p1(b); renegociar_p2_p3(b)
    comp = composicao(b, b.obl["N"])
    assert comp == {"5.02.01": 24000, "5.02.02": 16000, "5.05.01": 4000, "5.07.01": 4000, "5.07.02": 3000}
    assert sum(comp.values()) == 51000


def test_banco_barra_o_que_o_app_poderia_errar():
    b = base(); compras_na_fatura(b)
    t = b.tx("2026-07-21", "x")
    with pytest.raises(sqlite3.IntegrityError, match="exige titulo"):
        b.post(t, "2.01.01", -100)                                             # cartão sem título
    with pytest.raises(sqlite3.IntegrityError, match="outra conta"):
        b.post(t, "2.02.01", -100, obl="INV")                                  # título de outra conta
    with pytest.raises(sqlite3.IntegrityError, match="imutavel"):
        b.db.execute("UPDATE postings SET amount_cents=1")
    with pytest.raises(sqlite3.IntegrityError, match="imutavel"):
        b.db.execute("DELETE FROM transactions")
    with pytest.raises(sqlite3.IntegrityError, match="imutaveis"):
        b.db.execute("UPDATE obligations SET account_id=1")
    with pytest.raises(sqlite3.IntegrityError):
        b.db.execute("INSERT INTO postings (transaction_id, account_id, amount_cents, competence_month)"
                     " VALUES (?,?,?,?)", (t, b.acc["5.02.01"], 1, "2026-07-15"))  # competência não é dia 01
