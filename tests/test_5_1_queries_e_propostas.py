from datetime import date

import pytest

from salim.budget import set_budget
from salim.chart import seed_chart
from salim.ledger import AccountNotFoundError, Entry, post_transaction
from salim.obligations import register_bill
from salim.proposals import confirm_transaction, propose_simple, propose_transaction
from salim.queries import get_balance, get_budget_status, get_statement, get_upcoming_payables


def _mercado(session, dia, valor):
    post_transaction(session, event_date=date(2026, 8, dia), description="Mercado",
                     entries=[Entry("5.02.01", valor), Entry("1.01.01", -valor)])


# ---- consultas (5.1)
def test_get_balance_com_nome_e_data_de_corte(session):
    seed_chart(session)
    _mercado(session, 3, 10000)
    _mercado(session, 20, 5000)
    r = get_balance(session, "5.02.01", until=date(2026, 8, 10))
    assert r == {"code": "5.02.01", "name": "Supermercado", "balance_cents": 10000, "until": "2026-08-10"}
    assert get_balance(session, "5.02")["balance_cents"] == 15000          # grupo soma a subárvore
    assert get_balance(session, "1.01.01")["balance_cents"] == -15000


def test_get_balance_conta_inexistente(session):
    seed_chart(session)
    with pytest.raises(AccountNotFoundError):
        get_balance(session, "9.9.9")


def test_get_statement_limita_aos_ultimos_n(session):
    seed_chart(session)
    for d in (1, 2, 3):
        _mercado(session, d, 1000 * d)
    r = get_statement(session, "5.02.01", limit=2)
    assert [l["delta_cents"] for l in r] == [2000, 3000] and r[-1]["running_cents"] == 6000


def test_get_budget_status_devolve_dicts(session):
    seed_chart(session)
    set_budget(session, "5.02.01", 90000)
    _mercado(session, 5, 60000)
    r = get_budget_status(session, date(2026, 8, 1), today=date(2026, 8, 10))
    assert r[0]["code"] == "5.02.01" and r[0]["alert"] == "acima_do_ritmo"


def test_get_upcoming_payables_inclui_atrasados_e_respeita_janela(session):
    seed_chart(session)
    for mes, dia, nome in ((7, 20, "velha"), (8, 20, "proxima"), (10, 20, "longe")):
        register_bill(session, event_date=date(2026, mes, 1), description=nome, expense_account="5.01.03",
                      amount_cents=1000, due_date=date(2026, mes, dia), counterparty=nome)
    r = get_upcoming_payables(session, today=date(2026, 8, 12), days=30)
    assert [(p["counterparty"], p["status"]) for p in r] == [("velha", "atrasada"), ("proxima", "a_vencer")]


# ---- proposta e confirmação (5.6, 5.7)
def test_proposta_valida_nao_grava(session):
    seed_chart(session)
    p = propose_transaction(session, event_date=date(2026, 8, 5), description="Mercado",
                            entries=[{"account_code": "5.02.01", "amount_cents": 5000},
                                     {"account_code": "1.01.01", "amount_cents": -5000}])
    assert p["ok"] and p["errors"] == []
    assert [(e["account_code"], e["account_name"], e["amount_cents"]) for e in p["entries"]] == [
        ("5.02.01", "Supermercado", 5000), ("1.01.01", "Conta Corrente", -5000)]
    assert get_balance(session, "5.02.01")["balance_cents"] == 0


def test_proposta_invalida_lista_os_erros(session):
    seed_chart(session)
    p = propose_transaction(session, event_date=date(2026, 8, 5), description="x",
                            entries=[{"account_code": "5.02.01", "amount_cents": 5000},
                                     {"account_code": "1.01.01", "amount_cents": -4000}])
    assert not p["ok"] and "zero" in p["errors"][0]
    p = propose_transaction(session, event_date=date(2026, 8, 5), description="x",
                            entries=[{"account_code": "9.9.9", "amount_cents": 1}, {"account_code": "1.01.01", "amount_cents": -1}])
    assert not p["ok"] and "9.9.9" in p["errors"][0]


def test_propose_simple_monta_debito_e_credito(session):
    seed_chart(session)
    p = propose_simple(session, event_date=date(2026, 8, 5), description="Mercado", amount_cents=5000,
                       debit_account="5.02.01", credit_account="1.01.01")
    assert p["ok"] and [e["amount_cents"] for e in p["entries"]] == [5000, -5000]
    assert not propose_simple(session, event_date=date(2026, 8, 5), description="x", amount_cents=0,
                              debit_account="5.02.01", credit_account="1.01.01")["ok"]


def test_confirmar_grava_e_e_idempotente_por_external_ref(session):
    seed_chart(session)
    p = propose_simple(session, event_date=date(2026, 8, 5), description="Mercado", amount_cents=5000,
                       debit_account="5.02.01", credit_account="1.01.01")
    a = confirm_transaction(session, p, source="telegram", external_ref="tg:1")
    b = confirm_transaction(session, p, source="telegram", external_ref="tg:1")
    assert not a["duplicate"] and b["duplicate"] and a["transaction_id"] == b["transaction_id"]
    assert get_balance(session, "5.02.01")["balance_cents"] == 5000


def test_nao_confirma_proposta_invalida(session):
    seed_chart(session)
    p = propose_transaction(session, event_date=date(2026, 8, 5), description="x",
                            entries=[{"account_code": "5.02.01", "amount_cents": 5000}])
    with pytest.raises(ValueError, match="inválida"):
        confirm_transaction(session, p, source="mcp")


def test_confirmar_revalida_proposta_adulterada(session):
    seed_chart(session)
    p = propose_simple(session, event_date=date(2026, 8, 5), description="Mercado", amount_cents=5000,
                       debit_account="5.02.01", credit_account="1.01.01")
    p["entries"][0]["amount_cents"] = 9999                                 # alguém mexeu depois de validar
    with pytest.raises(ValueError, match="inválida"):
        confirm_transaction(session, p, source="mcp")
    assert get_balance(session, "5.02.01")["balance_cents"] == 0
