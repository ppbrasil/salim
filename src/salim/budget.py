"""Orçamento por competência (mês), fora do razão: só lê o que foi lançado."""
import calendar
from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from salim.db import sum_cents
from salim.ledger import _subtree_ids, month_start
from salim.models import Account, AccountType, BudgetLine, Posting

PROFILES = ("spread", "lump")


class BudgetError(Exception):
    pass


def _account(session: Session, code: str) -> Account:
    conta = session.execute(select(Account).where(Account.code == code)).scalar_one_or_none()
    if conta is None:
        raise BudgetError(f"conta inexistente: {code}")
    return conta


def set_budget(
    session: Session, account_code: str, amount_cents: int, *, month: date | None = None,
    profile: str = "spread", day_of_month: int | None = None,
) -> BudgetLine:
    """Cria ou atualiza a meta. month=None é o mês padrão; um mês específico sobrescreve o padrão."""
    if amount_cents < 0:
        raise BudgetError("valor do orçamento não pode ser negativo")
    if profile not in PROFILES:
        raise BudgetError(f"perfil inválido: {profile} (use spread ou lump)")
    if profile == "lump" and not day_of_month:
        raise BudgetError("perfil pontual exige o dia do mês")
    if day_of_month is not None and not 1 <= day_of_month <= 31:
        raise BudgetError("dia do mês deve estar entre 1 e 31")
    conta = _account(session, account_code)
    if conta.type not in (AccountType.EXPENSE, AccountType.INCOME):
        raise BudgetError("só conta de despesa ou receita tem orçamento")
    mes = month_start(month) if month else None
    q = select(BudgetLine).where(BudgetLine.account_id == conta.id)
    q = q.where(BudgetLine.month.is_(None) if mes is None else BudgetLine.month == mes)
    linha = session.execute(q).scalar_one_or_none()
    if linha is None:
        linha = BudgetLine(account_id=conta.id, month=mes)
        session.add(linha)
    linha.amount_cents, linha.profile = amount_cents, profile
    linha.day_of_month = day_of_month if profile == "lump" else None
    session.commit()
    return linha


def effective_budget(session: Session, account_code: str, month: date) -> BudgetLine | None:
    conta = _account(session, account_code)
    return _effective(session, conta.id, month_start(month))


def _effective(session: Session, account_id: int, month: date) -> BudgetLine | None:
    linhas = session.execute(
        select(BudgetLine).where(BudgetLine.account_id == account_id, (BudgetLine.month == month) | BudgetLine.month.is_(None))
    ).scalars().all()
    especifica = [l for l in linhas if l.month is not None]
    return (especifica or linhas or [None])[0]


@dataclass
class BudgetStatus:
    code: str
    name: str
    profile: str
    budget_cents: int
    actual_cents: int
    expected_cents: int       # quanto já "deveria" ter sido gasto na data de hoje
    remaining_cents: int
    pct_used: int | None
    alert: str                # ok | acima_do_ritmo | estourado


def _expected(linha: BudgetLine, month: date, today: date) -> int:
    atual = month_start(today)
    if month > atual:
        return 0
    if month < atual:
        return linha.amount_cents
    dias = calendar.monthrange(month.year, month.month)[1]
    if linha.profile == "lump":
        return linha.amount_cents if today.day >= min(linha.day_of_month, dias) else 0
    return linha.amount_cents * today.day // dias


def _actual(session: Session, conta: Account, month: date) -> int:
    bruto = session.execute(
        select(sum_cents(Posting.amount_cents))
        .where(Posting.account_id.in_(_subtree_ids(session, conta)), Posting.competence_month == month)
    ).scalar_one()
    return bruto if conta.type == AccountType.EXPENSE else -bruto


def budget_vs_actual(session: Session, month: date, today: date) -> list[BudgetStatus]:
    """Orçado × realizado por competência; o realizado de uma conta-grupo soma a subárvore."""
    month = month_start(month)
    contas = session.execute(select(Account).where(
        Account.id.in_(select(BudgetLine.account_id)))).scalars().all()
    saida = []
    for conta in sorted(contas, key=lambda c: c.code):
        linha = _effective(session, conta.id, month)
        if linha is None:
            continue
        real = _actual(session, conta, month)
        previsto = _expected(linha, month, today)
        pct = real * 100 // linha.amount_cents if linha.amount_cents else (0 if real == 0 else None)
        alerta = "ok"
        if conta.type == AccountType.EXPENSE:
            if real > linha.amount_cents:
                alerta = "estourado"
            elif linha.profile == "spread" and real > previsto:
                alerta = "acima_do_ritmo"
        saida.append(BudgetStatus(conta.code, conta.name, linha.profile, linha.amount_cents, real, previsto,
                                  linha.amount_cents - real, pct, alerta))
    return saida
