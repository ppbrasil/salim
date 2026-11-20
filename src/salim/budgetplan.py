"""Planejar o orçamento: o valor padrão de cada linha ao lado da média dos últimos meses fechados.

Orçamento e realizado seguem por competência (mês). A média usa os `months` meses fechados antes do mês corrente, e
só a partir do primeiro mês com movimento, para quem começou há pouco não ter a média diluída por meses vazios.
"""
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from salim import budget as bud
from salim import benchmark, chartcfg
from salim.db import sum_cents
from salim.ledger import month_start
from salim.models import Account, AccountType, BudgetLine, Posting


@dataclass
class PlanLine:
    code: str
    name: str
    avg_cents: int
    monthly: list[int]
    budget_cents: int | None          # padrão definido; None = sem orçamento
    profile: str = "spread"
    day_of_month: int | None = None
    share_pct: int | None = None      # fatia do orçamento total do tipo


@dataclass
class PlanGroup:
    code: str
    name: str
    is_group: bool                    # False = linha solta no primeiro nível (uma linha só)
    lines: list[PlanLine] = field(default_factory=list)
    avg_cents: int = 0
    monthly: list[int] = field(default_factory=list)
    budget_cents: int = 0             # soma das linhas
    share_pct: int | None = None
    peer: benchmark.Peer | None = None   # comparativo com a média das famílias brasileiras


@dataclass
class Plan:
    kind: str
    months: list[date]
    n_months: int
    groups: list[PlanGroup]
    total_avg_cents: int
    total_budget_cents: int


def _shift(d: date, k: int) -> date:
    idx = d.year * 12 + d.month - 1 + k
    return date(idx // 12, idx % 12 + 1, 1)


def _janela(session: Session, today: date, months: int) -> list[date]:
    atual = month_start(today)
    fim = _shift(atual, -1)
    primeiro = session.execute(
        select(func.min(Posting.competence_month)).join(Account, Account.id == Posting.account_id)
        .where(Account.type.in_([AccountType.EXPENSE, AccountType.INCOME]))).scalar_one()
    if primeiro is None:
        return []
    primeiro = month_start(primeiro if isinstance(primeiro, date) else date.fromisoformat(str(primeiro)))
    inicio = max(primeiro, _shift(atual, -months))
    out, m = [], inicio
    while m <= fim:
        out.append(m)
        m = _shift(m, 1)
    return out


def build_plan(session: Session, kind: str, today: date, months: int = 6) -> Plan:
    janela = _janela(session, today, months)
    sinal = 1 if kind == "expense" else -1
    por_conta: dict[str, list[int]] = {}
    if janela:
        for codigo, mes, cents in session.execute(
                select(Account.code, Posting.competence_month, sum_cents(Posting.amount_cents))
                .join(Account, Account.id == Posting.account_id)
                .where(Account.code.like(("5" if kind == "expense" else "4") + ".%"),
                       Posting.competence_month >= janela[0], Posting.competence_month <= janela[-1])
                .group_by(Account.code, Posting.competence_month)).all():
            mes = mes if isinstance(mes, date) else date.fromisoformat(str(mes))
            por_conta.setdefault(codigo, [0] * len(janela))[janela.index(month_start(mes))] += sinal * cents
    zeros = lambda: [0] * len(janela)
    soma = lambda *listas: [sum(v) for v in zip(*listas)] if listas else zeros()

    padrao = {}
    ids = dict(session.execute(select(Account.code, Account.id)).all())
    por_id = {l.account_id: l for l in session.execute(select(BudgetLine).where(BudgetLine.month.is_(None))).scalars()}
    for codigo, i in ids.items():
        if i in por_id:
            padrao[codigo] = por_id[i]

    def linha(codigo, nome, filhos):
        mensal = soma(por_conta.get(codigo, zeros()), *[por_conta.get(f.code, zeros()) for f in filhos])
        b = padrao.get(codigo)
        return PlanLine(codigo, nome, sum(mensal) // len(janela) if janela else 0, mensal,
                        b.amount_cents if b else None, b.profile if b else "spread", b.day_of_month if b else None)

    grupos: list[PlanGroup] = []
    for g in chartcfg.settings_tree(session, kind):
        if g.is_group:
            linhas = [linha(l.code, l.name, l.children) for l in g.lines]
        else:
            linhas = [linha(g.code, g.name, [])]
        grupos.append(PlanGroup(
            g.code, g.name, g.is_group, linhas, sum(l.avg_cents for l in linhas), soma(*[l.monthly for l in linhas]),
            sum(l.budget_cents or 0 for l in linhas)))
    total = sum(g.budget_cents for g in grupos)
    for g in grupos:
        g.share_pct = round(100 * g.budget_cents / total) if total else None
        ref = benchmark.reference_bps(g.name) if kind == "expense" else None
        if ref is not None:
            if total:
                g.peer = benchmark.position(round(10000 * g.budget_cents / total), ref)
            elif sum(x.avg_cents for x in grupos):
                g.peer = benchmark.position(round(10000 * g.avg_cents / sum(x.avg_cents for x in grupos)), ref, "gasto")
        for l in g.lines:
            l.share_pct = round(100 * l.budget_cents / total) if total and l.budget_cents is not None else None
    return Plan(kind, janela, len(janela), grupos, sum(g.avg_cents for g in grupos), total)


def save_plan(session: Session, values: dict[str, int | None]) -> int:
    """Grava o orçamento padrão das linhas informadas (None = não mexe). Mantém perfil e dia já definidos.
    Devolve quantas linhas mudaram."""
    mudou = 0
    for codigo, cents in values.items():
        if cents is None:
            continue
        atual = None
        conta = session.execute(select(Account).where(Account.code == codigo)).scalar_one_or_none()
        if conta is not None:
            atual = session.execute(select(BudgetLine).where(
                BudgetLine.account_id == conta.id, BudgetLine.month.is_(None))).scalar_one_or_none()
        if atual is not None and atual.amount_cents == cents:
            continue
        perfil = atual.profile if atual else "spread"
        dia = atual.day_of_month if atual else None
        bud.set_budget(session, codigo, cents, profile=perfil, day_of_month=dia)
        mudou += 1
    return mudou
