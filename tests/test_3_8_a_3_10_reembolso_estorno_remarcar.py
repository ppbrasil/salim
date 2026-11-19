from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from salim.chart import seed_chart
from salim.ledger import balance, create_account, reverse_transaction
from salim.models import AccountType
from salim.obligations import (
    ObligationError, consolidate_obligations, get_obligation, list_obligations, register_bill,
    register_card_purchase, register_reimbursable_expense, reschedule_obligation, settle_obligations,
)


def _cartao(session):
    seed_chart(session)
    create_account(session, code="2.01.01", name="Nubank", type=AccountType.LIABILITY, parent_code="2.01",
                   tracks_obligations=True, closing_day=25, due_day=5)


def test_reembolso_so_a_minha_parte_e_despesa_e_a_do_joao_vira_titulo_a_receber(session):
    _cartao(session)
    r = register_reimbursable_expense(
        session, event_date=date(2026, 7, 22), description="Jantar com o João", expense_account="5.02.02",
        my_share_cents=10000, other_share_cents=10000, counterparty="João", due_date=date(2026, 8, 30),
        payer_account_code="2.01.01")
    assert balance(session, "5.02.02") == 10000                      # só a minha metade pesa no resultado
    assert balance(session, "2.01.01") == 20000                      # mas o cartão foi cobrado por tudo
    assert get_obligation(session, r.id, today=date(2026, 9, 10)).status == "atrasada"
    settle_obligations(session, event_date=date(2026, 8, 12), items=[(r.id, None)], cash_account_code="1.01.01",
                       description="João pagou")
    assert balance(session, "1.01.01") == 10000                      # entrada de caixa
    assert get_obligation(session, r.id, today=date(2026, 9, 10)).status == "quitada"


def test_reembolso_pago_em_dinheiro(session):
    seed_chart(session)
    r = register_reimbursable_expense(
        session, event_date=date(2026, 7, 22), description="Táxi", expense_account="5.03.01",
        my_share_cents=3000, other_share_cents=3000, counterparty="Ana", due_date=date(2026, 8, 1),
        payer_account_code="1.01.01")
    assert balance(session, "1.01.01") == -6000 and get_obligation(session, r.id, date(2026, 7, 23)).balance_cents == 3000


def test_estorno_de_pagamento_reabre_o_titulo(session):
    seed_chart(session)
    o = register_bill(session, event_date=date(2026, 8, 10), description="Luz", expense_account="5.01.03",
                      amount_cents=10000, due_date=date(2026, 8, 20))
    pg = settle_obligations(session, event_date=date(2026, 8, 20), items=[(o.id, None)], cash_account_code="1.01.01")
    assert get_obligation(session, o.id, today=date(2026, 8, 25)).status == "quitada"
    reverse_transaction(session, pg.id, event_date=date(2026, 8, 25))
    v = get_obligation(session, o.id, today=date(2026, 8, 25))
    assert (v.status, v.balance_cents, v.days_late) == ("atrasada", 10000, 5)
    assert balance(session, "1.01.01") == 0


def test_remarcar_muda_so_vencimento_e_data_planejada(session):
    seed_chart(session)
    o = register_bill(session, event_date=date(2026, 8, 10), description="Luz", expense_account="5.01.03",
                      amount_cents=10000, due_date=date(2026, 8, 20))
    reschedule_obligation(session, o.id, planned_date=date(2026, 8, 28))
    v = get_obligation(session, o.id, today=date(2026, 8, 25))
    assert (v.due_date, v.planned_date, v.status) == (date(2026, 8, 20), date(2026, 8, 28), "atrasada")
    reschedule_obligation(session, o.id, due_date=date(2026, 9, 1), clear_planned=True)
    v = get_obligation(session, o.id, today=date(2026, 8, 25))
    assert (v.due_date, v.planned_date, v.status) == (date(2026, 9, 1), None, "a_vencer")


def test_remarcar_titulo_inexistente(session):
    seed_chart(session)
    with pytest.raises(ObligationError):
        reschedule_obligation(session, 999, due_date=date(2026, 9, 1))


def test_nao_consolida_o_mesmo_titulo_duas_vezes(session):
    seed_chart(session)
    o = register_bill(session, event_date=date(2026, 8, 10), description="Luz", expense_account="5.01.03",
                      amount_cents=10000, due_date=date(2026, 8, 20))
    with pytest.raises(ObligationError, match="repetido"):
        consolidate_obligations(session, [o.id, o.id], event_date=date(2026, 9, 1), due_date=date(2026, 9, 30))
    assert balance(session, "2.04.01") == 0
