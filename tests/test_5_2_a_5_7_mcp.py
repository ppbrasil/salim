import asyncio
import json
from datetime import date

import pytest

from salim.budget import set_budget
from salim.chart import seed_chart
from salim.mcp_server import build_server
from salim.obligations import register_bill

HOJE = date(2026, 8, 12)


@pytest.fixture
def mcp(session):
    seed_chart(session)
    return build_server(lambda: _Ctx(session), clock=lambda: HOJE)


class _Ctx:
    """Contexto que entrega a sessão do teste sem fechá-la."""
    def __init__(self, s): self.s = s
    def __enter__(self): return self.s
    def __exit__(self, *a): return False


def chamar(server, nome, **args):
    r = asyncio.run(server.call_tool(nome, args))
    return json.loads(r.content[0].text)


def test_lista_as_ferramentas_esperadas(mcp):
    nomes = {t.name for t in asyncio.run(mcp.list_tools())}
    assert nomes == {"get_balance", "get_statement", "get_budget_status", "get_upcoming_payables",
                     "propose_transaction", "confirm_transaction"}


def test_get_balance_e_erro_amigavel(mcp):
    chamar(mcp, "confirm_transaction", proposal=chamar(mcp, "propose_transaction", description="Mercado", amount_cents=5000,
                                                         debit_account="5.02.01", credit_account="1.01.01",
                                                         event_date="2026-08-05"))
    assert chamar(mcp, "get_balance", code="5.02.01")["data"]["balance_cents"] == 5000
    r = chamar(mcp, "get_balance", code="9.9.9")
    assert r["ok"] is False and "9.9.9" in r["error"]


def test_get_statement_com_limite(mcp):
    for v in (100, 200, 300):
        p = chamar(mcp, "propose_transaction", description="x", amount_cents=v, debit_account="5.02.01",
                   credit_account="1.01.01", event_date="2026-08-05")
        chamar(mcp, "confirm_transaction", proposal=p)
    r = chamar(mcp, "get_statement", code="5.02.01", limit=2)
    assert [l["delta_cents"] for l in r["data"]] == [200, 300]


def test_get_budget_status_usa_o_mes_corrente_por_padrao(mcp, session):
    set_budget(session, "5.02.01", 90000)
    r = chamar(mcp, "get_budget_status")
    assert r["data"][0]["code"] == "5.02.01" and r["data"][0]["budget_cents"] == 90000


def test_get_upcoming_payables(mcp, session):
    register_bill(session, event_date=date(2026, 8, 1), description="Luz", expense_account="5.01.03",
                  amount_cents=10000, due_date=date(2026, 8, 20), counterparty="Copel")
    r = chamar(mcp, "get_upcoming_payables", days=15)
    assert [(p["counterparty"], p["balance_cents"]) for p in r["data"]] == [("Copel", 10000)]


def test_propor_nao_grava_e_confirmar_grava_uma_vez(mcp):
    p = chamar(mcp, "propose_transaction", description="Mercado", amount_cents=5000, debit_account="5.02.01",
               credit_account="1.01.01", event_date="2026-08-05")
    assert p["ok"] and chamar(mcp, "get_balance", code="5.02.01")["data"]["balance_cents"] == 0
    a = chamar(mcp, "confirm_transaction", proposal=p, external_ref="mcp:1")
    b = chamar(mcp, "confirm_transaction", proposal=p, external_ref="mcp:1")
    assert a["data"]["duplicate"] is False and b["data"]["duplicate"] is True
    assert chamar(mcp, "get_balance", code="5.02.01")["data"]["balance_cents"] == 5000


def test_confirmar_proposta_invalida_devolve_erro(mcp):
    p = chamar(mcp, "propose_transaction", description="x", amount_cents=0, debit_account="5.02.01",
               credit_account="1.01.01", event_date="2026-08-05")
    assert p["ok"] is False
    r = chamar(mcp, "confirm_transaction", proposal=p)
    assert r["ok"] is False and "inválida" in r["error"]


def test_data_padrao_do_lancamento_e_hoje(mcp):
    p = chamar(mcp, "propose_transaction", description="x", amount_cents=100, debit_account="5.02.01",
               credit_account="1.01.01")
    assert p["event_date"] == "2026-08-12"
