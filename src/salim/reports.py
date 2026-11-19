"""Relatórios de leitura sobre o razão: DRE (competência), caixa executado e caixa futuro."""
from dataclasses import dataclass
from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session

from salim.ledger import month_start
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
    meses = {_ym(_shift_month(primeiro, k)): [0, 0, 0] for k in range(months)}
    for esperado, cents in session.execute(text("SELECT expected_date, expected_cents FROM v_cash_future")).all():
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
    out, saldo = [], abertura
    for ym, (i, o, late) in meses.items():
        saldo += i - o
        out.append(FutureMonth(ym, i, o, late, saldo))
    return out
