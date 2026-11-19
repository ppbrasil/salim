"""Camada única de consulta: devolve dicts simples (JSON) para API, MCP e Telegram."""
from dataclasses import asdict
from datetime import date, timedelta

from sqlalchemy.orm import Session

from salim import budget, ledger, obligations


def get_balance(session: Session, code: str, until: date | None = None) -> dict:
    conta = ledger.get_account(session, code)
    return {"code": conta.code, "name": conta.name, "balance_cents": ledger.balance(session, code, until),
            "until": until.isoformat() if until else None}


def get_statement(session: Session, code: str, limit: int | None = None) -> list[dict]:
    linhas = ledger.statement(session, code)
    return linhas[-limit:] if limit else linhas


def get_budget_status(session: Session, month: date, today: date) -> list[dict]:
    return [asdict(l) for l in budget.budget_vs_actual(session, month, today)]


def _obligation_dict(v: obligations.ObligationView) -> dict:
    d = asdict(v)
    return {k: (x.isoformat() if isinstance(x, date) else x) for k, x in d.items()}


def get_upcoming_payables(session: Session, today: date, days: int = 30) -> list[dict]:
    """Títulos a pagar vencidos ou que vencem em até `days` dias, por vencimento."""
    limite = today + timedelta(days=days)
    itens = [v for v in obligations.list_obligations(session, today)
             if v.direction == "pagar" and v.balance_cents > 0 and v.due_date <= limite]
    return [_obligation_dict(v) for v in sorted(itens, key=lambda v: (v.due_date, v.id))]
