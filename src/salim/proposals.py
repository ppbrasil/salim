"""Proposta → confirmação: nada é gravado até alguém confirmar (usado por MCP e Telegram)."""
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from salim import ledger
from salim.models import Transaction


def propose_transaction(session: Session, *, event_date: date, description: str, entries: list[dict]) -> dict:
    """Valida um lançamento sem gravar. Devolve {ok, errors, ...} pronto para mostrar e depois confirmar."""
    erros, linhas = [], []
    try:
        validas = [ledger.Entry(e["account_code"], int(e["amount_cents"])) for e in entries]
        contas = ledger._check_entries(session, validas)
        linhas = [{"account_code": c.code, "account_name": c.name, "amount_cents": e.amount_cents}
                  for c, e in zip(contas, validas)]
    except ledger.AccountNotFoundError as e:
        erros.append(f"conta inexistente: {e}")
    except (ledger.InvalidTransactionError, KeyError, ValueError) as e:
        erros.append(str(e))
    if not linhas:
        linhas = [{"account_code": e.get("account_code"), "account_name": None, "amount_cents": e.get("amount_cents")}
                  for e in entries]
    return {"ok": not erros, "errors": erros, "event_date": event_date.isoformat(),
            "description": description, "entries": linhas}


def propose_simple(session: Session, *, event_date: date, description: str, amount_cents: int,
                   debit_account: str, credit_account: str) -> dict:
    return propose_transaction(session, event_date=event_date, description=description, entries=[
        {"account_code": debit_account, "amount_cents": amount_cents},
        {"account_code": credit_account, "amount_cents": -amount_cents}])


def confirm_transaction(session: Session, proposal: dict, *, source: str, external_ref: str | None = None) -> dict:
    """Grava uma proposta. Revalida tudo; com external_ref repetido devolve o lançamento já existente."""
    if external_ref:
        existente = session.execute(select(Transaction).where(Transaction.external_ref == external_ref)).scalar_one_or_none()
        if existente is not None:
            return {"transaction_id": existente.id, "duplicate": True}
    de_novo = propose_transaction(session, event_date=date.fromisoformat(proposal["event_date"]),
                                  description=proposal["description"], entries=proposal["entries"])
    if not de_novo["ok"]:
        raise ValueError("proposta inválida: " + "; ".join(de_novo["errors"]))
    tx = ledger.post_transaction(
        session, event_date=date.fromisoformat(proposal["event_date"]), description=proposal["description"],
        entries=[ledger.Entry(e["account_code"], e["amount_cents"]) for e in proposal["entries"]],
        source=source, external_ref=external_ref)
    return {"transaction_id": tx.id, "duplicate": False}
