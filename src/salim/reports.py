"""Relatórios de leitura sobre o razão: DRE (competência), caixa executado e caixa futuro."""
from dataclasses import dataclass
from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session

from salim import budget as _budget
from salim.ledger import account_tree, month_start
from salim.obligations import _shift


def _months(start: date, end: date) -> list[date]:
    out, y, m = [], start.year, start.month
    while (y, m) <= (end.year, end.month):
        out.append(date(y, m, 1))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _as_date(v) -> date:
    """SQLite devolve datas de views como texto ISO; o Postgres devolve date."""
    return date.fromisoformat(v) if isinstance(v, str) else v


def _ym(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


# ------------------------------------------------------------------ DRE
@dataclass
class DreLine:
    code: str
    name: str
    type: str
    amount_cents: int


@dataclass
class Dre:
    start: date
    end: date
    lines: list[DreLine]
    income_cents: int
    expense_cents: int

    @property
    def result_cents(self) -> int:
        return self.income_cents - self.expense_cents


def dre(session: Session, start: date, end: date | None = None) -> Dre:
    """Resultado por competência no intervalo de meses (inclui o que ainda não foi pago)."""
    start, end = month_start(start), month_start(end or start)
    rows = session.execute(text("""
        SELECT d.account_code, a.name, d.type, CAST(SUM(d.amount_cents) AS BIGINT)
        FROM v_dre d JOIN accounts a ON a.code = d.account_code
        WHERE d.month BETWEEN :s AND :e
        GROUP BY d.account_code, a.name, d.type HAVING SUM(d.amount_cents) <> 0
        ORDER BY d.account_code"""), {"s": start.isoformat(), "e": end.isoformat()}).all()
    lines = [DreLine(code, name, typ, cents) for code, name, typ, cents in rows]
    return Dre(start, end, lines,
               income_cents=sum(l.amount_cents for l in lines if l.type == "income"),
               expense_cents=sum(l.amount_cents for l in lines if l.type == "expense"))


def first_activity_month(session: Session) -> date | None:
    """Primeiro mês de competência com lançamento em receita ou despesa."""
    v = session.execute(text("SELECT MIN(month) FROM v_dre")).scalar_one()
    return month_start(_as_date(v)) if v else None


def last_activity_month(session: Session) -> date | None:
    v = session.execute(text("SELECT MAX(month) FROM v_dre")).scalar_one()
    return month_start(_as_date(v)) if v else None


# ------------------------------------------------------------------ DRE mês a mês
@dataclass
class DreRow:
    code: str
    name: str
    type: str
    depth: int
    is_group: bool
    cents: list[int]          # um valor por mês, na ordem de DreMonthly.months

    @property
    def total_cents(self) -> int:
        return sum(self.cents)


@dataclass
class DreMonthly:
    months: list[str]         # 'AAAA-MM'
    rows: list[DreRow]        # árvore (receitas e despesas) em ordem de código; grupos somam os filhos
    income: list[int]
    expense: list[int]

    @property
    def result(self) -> list[int]:
        return [i - e for i, e in zip(self.income, self.expense)]


def dre_monthly(session: Session, start: date, end: date) -> DreMonthly:
    """DRE por competência com um mês por coluna. Só entram contas (e grupos) com movimento no período."""
    meses = [_ym(m) for m in _months(month_start(start), month_start(end))]
    col = {ym: i for i, ym in enumerate(meses)}
    dados: dict[str, list[int]] = {}
    for mes, code, cents in session.execute(text("""
            SELECT d.month, d.account_code, CAST(d.amount_cents AS BIGINT) FROM v_dre d
            WHERE d.month BETWEEN :s AND :e"""), {"s": month_start(start).isoformat(),
                                                  "e": month_start(end).isoformat()}).all():
        ym = _ym(_as_date(mes))
        if ym in col:
            dados.setdefault(code, [0] * len(meses))[col[ym]] += cents
    arvore = [(d, c) for d, c in account_tree(session) if c.type.value in ("income", "expense")]
    soma: dict[int, list[int]] = {c.id: list(dados.get(c.code, [0] * len(meses))) for _, c in arvore}
    por_id = {c.id: c for _, c in arvore}
    for _, c in reversed(arvore):          # filhos vêm depois do pai: somar de baixo para cima
        if c.parent_id in soma:
            soma[c.parent_id] = [a + b for a, b in zip(soma[c.parent_id], soma[c.id])]
    rows = [DreRow(c.code, c.name, c.type.value, d, c.is_group, soma[c.id])
            for d, c in arvore if any(soma[c.id])]
    topo = {c.type.value: soma[c.id] for _, c in arvore if c.parent_id is None or c.parent_id not in por_id}
    zero = [0] * len(meses)
    return DreMonthly(meses, rows, topo.get("income", zero), topo.get("expense", zero))


# ------------------------------------------------------------------ caixa executado
@dataclass
class CashMonth:
    month: str
    inflow_cents: int
    outflow_cents: int

    @property
    def net_cents(self) -> int:
        return self.inflow_cents - self.outflow_cents


def cash_executed(session: Session, start: date, end: date) -> list[CashMonth]:
    """Entradas e saídas das contas de caixa por mês da data do evento.

    Transferência entre contas de caixa soma zero e não aparece como entrada nem saída.
    """
    por_mes = {_ym(m): [0, 0] for m in _months(start, end)}
    rows = session.execute(text("""
        SELECT t.event_date, CAST(SUM(p.amount_cents) AS BIGINT)
        FROM postings p
        JOIN accounts a ON a.id = p.account_id AND a.is_cash
        JOIN transactions t ON t.id = p.transaction_id
        WHERE t.event_date >= :s AND t.event_date < :e
        GROUP BY t.id"""), {"s": month_start(start).isoformat(),
                            "e": _shift_month(month_start(end), 1).isoformat()}).all()
    for dia, net in rows:
        ym = _ym(_as_date(dia))
        if ym in por_mes and net:
            por_mes[ym][0 if net > 0 else 1] += abs(net)
    return [CashMonth(ym, i, o) for ym, (i, o) in por_mes.items()]


def _shift_month(d: date, k: int) -> date:
    y, m = _shift(d.year, d.month, k)
    return date(y, m, 1)


# ------------------------------------------------------------------ caixa futuro
@dataclass
class FutureMonth:
    month: str
    inflow_cents: int
    outflow_cents: int
    late_cents: int          # parte da saída que já está vencida (cai no mês corrente)
    closing_cents: int       # saldo de caixa projetado ao fim do mês
    cards_cents: int = 0     # parte da saída que são faturas de cartão

    @property
    def net_cents(self) -> int:
        return self.inflow_cents - self.outflow_cents


def cash_future(session: Session, today: date, months: int = 6) -> list[FutureMonth]:
    """Projeção: títulos em aberto na data planejada (ou vencimento); atrasados caem no mês corrente."""
    abertura = session.execute(text("""
        SELECT CAST(COALESCE(SUM(p.amount_cents), 0) AS BIGINT) FROM postings p
        JOIN accounts a ON a.id = p.account_id AND a.is_cash
        JOIN transactions t ON t.id = p.transaction_id
        WHERE t.event_date <= :hoje"""), {"hoje": today.isoformat()}).scalar_one()
    primeiro = month_start(today)
    meses = {_ym(_shift_month(primeiro, k)): [0, 0, 0, 0] for k in range(months)}
    for esperado, cents, tipo in session.execute(text(
            "SELECT f.expected_date, f.expected_cents, o.kind FROM v_cash_future f JOIN obligations o ON o.id = f.obligation_id")).all():
        esperado = _as_date(esperado)
        atrasado = esperado < today
        ym = _ym(primeiro) if atrasado else _ym(esperado)
        if ym not in meses:
            continue
        if cents > 0:
            meses[ym][0] += cents
        else:
            meses[ym][1] += -cents
            if atrasado:
                meses[ym][2] += -cents
            if tipo == "invoice":
                meses[ym][3] += -cents
    out, saldo = [], abertura
    for ym, (i, o, late, cartoes) in meses.items():
        saldo += i - o
        out.append(FutureMonth(ym, i, o, late, saldo, cartoes))
    return out


def cash_horizon(session: Session, today: date, minimo: int = 3, teto: int = 24) -> int:
    """Quantos meses à frente do mês corrente a projeção precisa cobrir: até o último título em aberto (faturas futuras
    de parcelas incluídas), entre `minimo` e `teto`."""
    ultimo = session.execute(text("SELECT MAX(expected_date) FROM v_cash_future")).scalar_one()
    if not ultimo:
        return minimo
    u, a = _as_date(ultimo), month_start(today)
    return max(minimo, min(teto, (u.year - a.year) * 12 + u.month - a.month))


# ------------------------------------------------------------------ caixa mês a mês (executado + previsto)
@dataclass
class CashMonthRow:
    month: str
    inflow_cents: int          # executado (data do evento)
    outflow_cents: int
    expected_in_cents: int     # a receber em aberto previsto para o mês (títulos)
    expected_out_cents: int    # a pagar em aberto previsto (inclui o já vencido no mês corrente)
    closing_cents: int         # saldo ao fim: realizado até hoje; projetado nos meses futuros
    is_future: bool
    is_current: bool
    budget_net_cents: int | None
    deviation_cents: int | None
    expected_cards_cents: int = 0   # parte do a pagar previsto que são faturas de cartão

    @property
    def net_cents(self) -> int:
        return self.inflow_cents - self.outflow_cents


@dataclass
class CashMonthly:
    months: list[CashMonthRow]


def first_cash_month(session: Session) -> date | None:
    v = session.execute(text("""
        SELECT MIN(t.event_date) FROM postings p JOIN accounts a ON a.id = p.account_id AND a.is_cash
        JOIN transactions t ON t.id = p.transaction_id""")).scalar_one()
    return month_start(_as_date(v)) if v else None


def cash_monthly(session: Session, start: date, end: date, today: date, future_months: int = 3) -> CashMonthly:
    """Uma linha por mês: o que entrou e saiu de fato, o saldo, o que os títulos preveem e o desvio contra o orçado.

    Meses depois de `end` (até `future_months`) entram só com a projeção dos títulos em aberto. O desvio compara o
    líquido do mês (no mês corrente: executado + previsto) com receitas − despesas do orçamento.
    """
    start, end, atual = month_start(start), month_start(end), month_start(today)
    ultimo = _shift_month(end, future_months)
    meses = _months(start, ultimo)
    executado = {m.month: m for m in cash_executed(session, start, end)}
    abertura = session.execute(text("""
        SELECT CAST(COALESCE(SUM(p.amount_cents), 0) AS BIGINT) FROM postings p
        JOIN accounts a ON a.id = p.account_id AND a.is_cash
        JOIN transactions t ON t.id = p.transaction_id WHERE t.event_date < :s"""),
        {"s": start.isoformat()}).scalar_one()
    previsto, proj_fecha = {}, {}
    if ultimo >= atual:
        n = (ultimo.year - atual.year) * 12 + ultimo.month - atual.month + 1
        for f in cash_future(session, today, n):
            previsto[f.month] = (f.inflow_cents, f.outflow_cents, f.cards_cents)
            proj_fecha[f.month] = f.closing_cents
    linhas, saldo = [], abertura
    for m in meses:
        ym = _ym(m)
        ex = executado.get(ym)
        entrou, saiu = (ex.inflow_cents, ex.outflow_cents) if ex else (0, 0)
        futuro, corrente = m > atual, m == atual
        pin, pout, pcard = previsto.get(ym, (0, 0, 0)) if m >= atual else (0, 0, 0)
        saldo += entrou - saiu
        fecha = proj_fecha.get(ym, saldo) if futuro else saldo
        orcado = _budget.budget_net_cents(session, m)
        liquido = entrou - saiu + (pin - pout if corrente or futuro else 0)
        linhas.append(CashMonthRow(ym, entrou, saiu, pin, pout, fecha, futuro, corrente, orcado,
                                   None if orcado is None else liquido - orcado, pcard))
    return CashMonthly(linhas)
