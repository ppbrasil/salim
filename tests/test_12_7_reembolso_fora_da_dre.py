"""12.7 Gasto que a empresa vai reembolsar: do meu bolso/cartão direto para 'a receber'. Não é despesa minha."""
from datetime import date

import pytest

from salim import obligations as obl
from salim import reports
from salim.chart import seed_chart
from salim.ledger import balance, create_account
from salim.models import AccountType


def _cartao(session):
    seed_chart(session)
    create_account(session, code="2.01.01", name="Santander", type=AccountType.LIABILITY, parent_code="2.01",
                   tracks_obligations=True, closing_day=25, due_day=5)


def test_gasto_no_cartao_vai_direto_para_a_receber_sem_tocar_a_dre(session):
    _cartao(session)
    pedido = obl.add_reimbursement_item(
        session, event_date=date(2026, 8, 17), description="Jantar cliente", amount_cents=20000,
        payer_account_code="2.01.01", reference="Viagem SP", counterparty="Tupi", due_date=date(2026, 9, 30))
    assert balance(session, "1.03.01") == 20000           # a Tupi me deve
    assert balance(session, "2.01.01") == 20000           # e a fatura do cartão me cobra: dois balanços
    dre = reports.dre(session, date(2026, 8, 1), date(2026, 8, 31))
    assert dre.expense_cents == 0 and dre.income_cents == 0
    assert obl.get_obligation(session, pedido.id, date(2026, 8, 20)).balance_cents == 20000


def test_segundo_item_no_mesmo_pedido_pago_do_caixa(session):
    _cartao(session)
    p = obl.add_reimbursement_item(session, event_date=date(2026, 8, 17), description="Hotel", amount_cents=50000,
                                   payer_account_code="2.01.01", reference="Viagem SP", counterparty="Tupi")
    obl.add_reimbursement_item(session, event_date=date(2026, 8, 18), description="Táxi", amount_cents=3000,
                               payer_account_code="1.01.01", obligation_id=p.id)
    assert balance(session, "1.03.01") == 53000 and balance(session, "1.01.01") == -3000
    assert reports.dre(session, date(2026, 8, 1), date(2026, 8, 31)).expense_cents == 0


def test_item_exige_uma_origem_despesa_ja_lancada_ou_pagador(session):
    _cartao(session)
    base = dict(event_date=date(2026, 8, 17), description="x", amount_cents=100, reference="v", counterparty="Tupi")
    with pytest.raises(obl.ObligationError):               # nem despesa nem pagador
        obl.add_reimbursement_item(session, **base)
    with pytest.raises(obl.ObligationError):               # os dois: ambíguo
        obl.add_reimbursement_item(session, expense_account="5.02.02", payer_account_code="2.01.01", **base)


def test_api_item_com_pagador_nao_cria_despesa(client):
    client.post("/accounts", json={"code": "2.01.01", "name": "Santander", "type": "liability", "parent_code": "2.01",
                                   "tracks_obligations": True, "closing_day": 25, "due_day": 5})
    r = client.post("/reimbursements", json={
        "event_date": "2026-08-17", "description": "Hotel", "amount_cents": 50000, "payer_account_code": "2.01.01",
        "reference": "Viagem SP", "counterparty": "Tupi", "due_date": "2026-09-30"})
    assert r.status_code == 201 and r.json()["balance_cents"] == 50000
    dre = client.get("/reports/dre", params={"start": "2026-08-01", "end": "2026-08-31"}).json()
    assert dre["expense_cents"] == 0
