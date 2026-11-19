"""Mais cenários difíceis sobre o MESMO modelo (docs/modelo.sql). Protótipo descartável."""
import calendar
from datetime import date

from test_cenario_critico import (
    base, compras_na_fatura, parcelar_fatura, pagar_p1, status, dre_por_mes,
)


def dre_por_conta(b):
    return {(r["month"], r["account_code"]): r["amount_cents"] for r in b.q("SELECT * FROM v_dre")}


# 1 -------------------------------------------------------------------------
def test_compra_parcelada_no_cartao_despesa_inteira_no_mes_da_compra():
    """R$ 300 em 3x no cartão. Competência CHEIA em out; o caixa sai em 3 faturas."""
    b = base()
    t = b.tx("2026-10-10", "TV em 3x", "purchase")
    for ref, close, due in [("2026-10", "2026-10-25", "2026-11-05"),
                            ("2026-11", "2026-11-25", "2026-12-05"),
                            ("2026-12", "2026-12-25", "2027-01-05")]:
        b.new_obl(f"INV{ref}", "2.01.01", t, "invoice", due, reference=ref, closing_date=close)
    b.post(t, "5.08.01", 30000)                               # competência = out (mês da compra)
    for ref in ("2026-10", "2026-11", "2026-12"):
        b.post(t, "2.01.01", -10000, obl=f"INV{ref}")
    assert dre_por_mes(b) == {"2026-10-01": 30000}            # nada nos meses seguintes
    fut = {r["expected_date"]: r["expected_cents"] for r in b.q("SELECT * FROM v_cash_future")}
    assert fut == {"2026-11-05": -10000, "2026-12-05": -10000, "2027-01-05": -10000}


# 2 -------------------------------------------------------------------------
def test_tres_contas_de_luz_atrasadas_pagas_numa_saida_com_tres_competencias():
    b = base()
    for mes, val in [("08", 10000), ("09", 11000), ("10", 12000)]:
        t = b.tx(f"2026-{mes}-10", f"Conta de luz {mes}", "purchase")
        b.new_obl(f"L{mes}", "2.02.02", t, "bill", f"2026-{mes}-20", reference=f"luz {mes}", counterparty="Copel")
        b.post(t, "5.01.03", val); b.post(t, "2.02.02", -val, obl=f"L{mes}")
    s = status(b, "2026-11-04")
    assert [s[f"luz {m}"][0] for m in ("08", "09", "10")] == ["atrasada"] * 3
    # paga tudo de uma vez, com multa e juros em linhas separadas
    t = b.tx("2026-11-05", "Pagamento das 3 contas de luz", "payment")
    for m, v in [("08", 10000), ("09", 11000), ("10", 12000)]:
        b.post(t, "2.02.02", v, obl=f"L{m}")
    b.post(t, "5.07.02", 660); b.post(t, "5.07.01", 300)
    b.post(t, "1.01.01", -33960)
    assert all(v[0] == "quitada" for v in status(b, "2026-11-05").values())
    d = dre_por_conta(b)
    assert d[("2026-08-01", "5.01.03")] == 10000 and d[("2026-09-01", "5.01.03")] == 11000 \
        and d[("2026-10-01", "5.01.03")] == 12000                       # luz fica nos meses de origem
    assert d[("2026-11-01", "5.07.02")] == 660 and d[("2026-11-01", "5.07.01")] == 300
    saidas = [r["net_cents"] for r in b.q("SELECT * FROM v_cash_executed")]
    assert saidas == [-33960]                                           # uma saída de caixa só


# 3 -------------------------------------------------------------------------
def test_reembolso_a_receber_e_recebimento():
    b = base()
    compras_na_fatura(b)                                                # cria INV e a conta do cartão
    t = b.tx("2026-07-22", "Jantar com o João (R$ 200)", "purchase")
    b.new_obl("R", "1.03.01", t, "reimbursement", "2026-08-30", reference="jantar", counterparty="João")
    b.post(t, "5.02.02", 10000)                                          # só a minha metade é despesa
    b.post(t, "1.03.01", 10000, obl="R")                                 # metade do João: a receber
    b.post(t, "2.01.01", -20000, obl="INV")                              # tudo foi no cartão
    assert dre_por_mes(b)["2026-07-01"] == 50000 + 10000                 # só +100 de despesa minha
    assert status(b, "2026-08-10")["jantar"] == ("a_vencer", 10000, 0)   # João ainda está no prazo
    assert status(b, "2026-09-10")["jantar"] == ("atrasada", 10000, 11)  # passou do prazo sem pagar
    fut = {r["expected_date"]: r["expected_cents"] for r in b.q("SELECT * FROM v_cash_future")}
    assert fut["2026-08-30"] == 10000                                    # entrada prevista (sinal +)
    t2 = b.tx("2026-08-12", "João pagou", "payment")
    b.post(t2, "1.01.01", 10000); b.post(t2, "1.03.01", -10000, obl="R")
    assert status(b, "2026-08-12")["jantar"][:2] == ("quitada", 0)


# 4 -------------------------------------------------------------------------
def test_pagamento_parcial_de_fatura_deixa_saldo_atrasado():
    b = base(); compras_na_fatura(b)
    t = b.tx("2026-08-05", "Pagamento mínimo da fatura", "payment")
    b.post(t, "2.01.01", 22000, obl="INV"); b.post(t, "1.01.01", -22000)
    assert status(b, "2026-08-05")["2026-07"][:2] == ("a_vencer", 88000)      # vence hoje: ainda não atrasou
    assert status(b, "2026-08-06")["2026-07"] == ("atrasada", 88000, 1)


# 5 -------------------------------------------------------------------------
def test_estorno_de_pagamento_reabre_o_titulo():
    b = base(); compras_na_fatura(b); parcelar_fatura(b); pagar_p1(b)
    assert status(b, "2026-09-30")["parc 1/5"][0] == "quitada"
    pago = b.txs[-1]
    t = b.tx("2026-09-30", "Estorno: pagamento parcela 1/5", "reversal")
    for r in b.q("SELECT p.account_id a, p.amount_cents c, p.competence_month m, p.obligation_id o "
                 "FROM postings p WHERE transaction_id=:t", t=pago):
        b.db.execute("INSERT INTO postings (transaction_id,account_id,amount_cents,competence_month,obligation_id)"
                     " VALUES (?,?,?,?,?)", (t, r["a"], -r["c"], r["m"], r["o"]))
    assert status(b, "2026-09-30")["parc 1/5"] == ("atrasada", 24000, 25)    # voltou a dever, vencida em 05/09


# 6 -------------------------------------------------------------------------
def test_orcamento_x_realizado_com_perfil_pontual_e_diluido():
    b = base()
    for conta, val in [("5.01.01", 300000), ("5.02.01", 80000)]:
        b.db.execute("INSERT INTO budget_lines (account_id, month, amount_cents, profile, day_of_month)"
                     " VALUES (?,NULL,?,?,?)",
                     (b.acc[conta], val, "lump" if conta == "5.01.01" else "spread", 5 if conta == "5.01.01" else None))
    t = b.tx("2026-11-05", "Aluguel", "purchase"); b.post(t, "5.01.01", 300000); b.post(t, "1.01.01", -300000)
    for d, v in [("2026-11-03", 40000), ("2026-11-12", 22000)]:
        t = b.tx(d, "Mercado", "purchase"); b.post(t, "5.02.01", v); b.post(t, "1.01.01", -v)
    hoje = date(2026, 11, 19)

    def linha(conta):
        orc = b.q("SELECT * FROM budget_lines WHERE account_id=:a", a=b.acc[conta])[0]
        real = b.q("SELECT COALESCE(SUM(amount_cents),0) s FROM postings WHERE account_id=:a AND competence_month=:m",
                   a=b.acc[conta], m="2026-11-01")[0]["s"]
        dias = calendar.monthrange(hoje.year, hoje.month)[1]
        esperado = (orc["amount_cents"] if hoje.day >= orc["day_of_month"] else 0) if orc["profile"] == "lump" \
            else orc["amount_cents"] * hoje.day // dias
        return orc["amount_cents"], real, esperado

    assert linha("5.01.01") == (300000, 300000, 300000)   # aluguel 100% no dia 5: esperado, sem alerta
    orc, real, esperado = linha("5.02.01")
    assert (orc, real) == (80000, 62000) and real > esperado   # dia 19: gastou 77,5% do mês; esperava ~63%
    assert esperado == 50666
