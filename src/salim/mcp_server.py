"""Servidor MCP do Salim: consulta e lançamento com confirmação, sobre a mesma camada do web e do Telegram.

Rodar:  python -m salim.mcp_server            (stdio)
        SALIM_MCP_TRANSPORT=streamable-http python -m salim.mcp_server
"""
import os
from datetime import date
from functools import wraps

from mcp.server.mcpserver import MCPServer

from salim import ledger, obligations, proposals, queries
from salim.clock import today as clock_today
from salim.budget import BudgetError

_BUSINESS = (ledger.AccountNotFoundError, ledger.InvalidAccountError, ledger.InvalidTransactionError,
             obligations.ObligationError, BudgetError, ValueError)


def _safe(fn):
    """Erro de negócio vira {ok: False, error} em vez de derrubar a chamada; o modelo lê e corrige."""
    @wraps(fn)
    def wrapper(*a, **kw):
        try:
            return {"ok": True, "data": fn(*a, **kw)}
        except ledger.AccountNotFoundError as e:
            return {"ok": False, "error": f"conta inexistente: {e}"}
        except _BUSINESS as e:
            return {"ok": False, "error": str(e)}
    return wrapper


def build_server(session_factory, clock=clock_today) -> MCPServer:
    server = MCPServer("salim", instructions=(
        "Controle financeiro por partidas dobradas. Valores em centavos (BRL). Débito positivo, crédito negativo. "
        "Para lançar: propose_transaction (não grava) → mostre ao usuário → confirm_transaction."))

    def _d(iso: str | None) -> date:
        return date.fromisoformat(iso) if iso else clock()

    @server.tool()
    @_safe
    def get_balance(code: str, until: str | None = None) -> dict:
        """Saldo de uma conta (ou grupo, somando a subárvore) em centavos; `until` = AAAA-MM-DD opcional."""
        with session_factory() as s:
            return queries.get_balance(s, code, date.fromisoformat(until) if until else None)

    @server.tool()
    @_safe
    def get_statement(code: str, limit: int | None = None) -> list:
        """Extrato da conta com saldo corrente; `limit` devolve só os últimos N movimentos."""
        with session_factory() as s:
            return queries.get_statement(s, code, limit)

    @server.tool()
    @_safe
    def get_budget_status(month: str | None = None) -> list:
        """Orçado × realizado por competência (mês AAAA-MM-01; padrão: mês atual) com alerta de ritmo."""
        with session_factory() as s:
            return queries.get_budget_status(s, _d(month), clock())

    @server.tool()
    @_safe
    def get_upcoming_payables(days: int = 30) -> list:
        """Contas a pagar atrasadas ou que vencem nos próximos `days` dias, por vencimento."""
        with session_factory() as s:
            return queries.get_upcoming_payables(s, clock(), days)

    @server.tool()
    def propose_transaction(description: str, amount_cents: int, debit_account: str, credit_account: str,
                            event_date: str | None = None) -> dict:
        """Valida um lançamento simples (débito/crédito) SEM gravar. Devolve a proposta para confirmar."""
        with session_factory() as s:
            return proposals.propose_simple(s, event_date=_d(event_date), description=description,
                                            amount_cents=amount_cents, debit_account=debit_account,
                                            credit_account=credit_account)

    @server.tool()
    @_safe
    def confirm_transaction(proposal: dict, external_ref: str | None = None) -> dict:
        """Grava uma proposta válida. Com `external_ref` repetido não duplica (devolve duplicate=true)."""
        with session_factory() as s:
            return proposals.confirm_transaction(s, proposal, source="mcp", external_ref=external_ref)

    return server


def main() -> None:
    from salim.app import _default_factory
    build_server(_default_factory()).run(os.environ.get("SALIM_MCP_TRANSPORT", "stdio"))


if __name__ == "__main__":
    main()
