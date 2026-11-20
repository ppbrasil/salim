"""Compra no cartão em fatura(s) informada(s): o banco processa com 1–2 dias de atraso e o fechamento varia,
então para carregar faturas reais o fechamento e o vencimento vêm do extrato, não da regra "dia X"."""
from datetime import date

import pytest

from salim.chart import seed_chart
from salim.ledger import balance, create_account
from salim.models import AccountType
from salim.obligations import ObligationError, list_obligations, register_card_purchase


def _cartao(session):
    seed_chart(session)
    create_account(session, code="2.01.01", name="Santander", type=AccountType.LIABILITY, parent_code="2.01",
                   tracks_obligations=True, closing_day=12, due_day=19)


def test_fatura_informada_vale_mais_que_o_dia_de_fechamento(session):
    _cartao(session)
    # 13/07 cairia na fatura de agosto pela regra (fecha dia 12); no extrato real está na de julho
    (f,) = register_card_purchase(session, card_code="2.01.01", event_date=date(2026, 7, 13), description="Padaria",
                                  items=[("5.99", 5000)], invoices=[(date(2026, 7, 13), date(2026, 7, 19))])
    assert (f.reference, f.closing_date, f.due_date) == ("2026-07", date(2026, 7, 13), date(2026, 7, 19))


def test_mesma_fatura_e_reaproveitada_e_soma(session):
    _cartao(session)
    inv = [(date(2026, 7, 13), date(2026, 7, 19))]
    (a,) = register_card_purchase(session, card_code="2.01.01", event_date=date(2026, 7, 1), description="a",
                                  items=[("5.99", 1000)], invoices=inv)
    (b,) = register_card_purchase(session, card_code="2.01.01", event_date=date(2026, 7, 13), description="b",
                                  items=[("5.99", 2500)], invoices=inv)
    assert a.id == b.id
    (v,) = list_obligations(session, today=date(2026, 7, 14))
    assert v.balance_cents == 3500


def test_parcelas_em_faturas_informadas(session):
    _cartao(session)
    inv = [(date(2026, 7, 13), date(2026, 7, 19)), (date(2026, 8, 12), date(2026, 8, 19)),
           (date(2026, 9, 14), date(2026, 9, 19))]
    faturas = register_card_purchase(session, card_code="2.01.01", event_date=date(2026, 7, 10), description="TV",
                                     items=[("5.99", 30000)], installments=3, invoices=inv)
    assert [(f.reference, f.due_date) for f in faturas] == [
        ("2026-07", date(2026, 7, 19)), ("2026-08", date(2026, 8, 19)), ("2026-09", date(2026, 9, 19))]
    assert balance(session, "5.99") == 30000


def test_quantidade_de_faturas_precisa_bater_com_as_parcelas(session):
    _cartao(session)
    with pytest.raises(ObligationError, match="faturas"):
        register_card_purchase(session, card_code="2.01.01", event_date=date(2026, 7, 10), description="x",
                               items=[("5.99", 3000)], installments=3, invoices=[(date(2026, 7, 13), date(2026, 7, 19))])


def test_estorno_no_cartao_reduz_a_fatura(session):
    _cartao(session)
    inv = [(date(2026, 8, 12), date(2026, 8, 19))]
    register_card_purchase(session, card_code="2.01.01", event_date=date(2026, 7, 20), description="Voo",
                           items=[("5.99", 15334)], invoices=inv)
    register_card_purchase(session, card_code="2.01.01", event_date=date(2026, 7, 20), description="Estorno voo",
                           items=[("5.99", -15334)], invoices=inv)
    (v,) = list_obligations(session, today=date(2026, 8, 13), include_settled=True)
    assert v.balance_cents == 0 and v.status == "quitada"
    assert balance(session, "5.99") == 0


def test_api_fatura_informada_e_tamanho_invalido(client):
    seed = client.post("/accounts", json={"code": "2.01.01", "name": "Santander", "type": "liability",
                                          "parent_code": "2.01", "tracks_obligations": True,
                                          "closing_day": 12, "due_day": 19})
    assert seed.status_code == 201
    corpo = {"card_code": "2.01.01", "event_date": "2026-07-13", "description": "Padaria",
             "items": [{"account_code": "5.99", "amount_cents": 5000}],
             "invoices": [{"closing_date": "2026-07-13", "due_date": "2026-07-19"}]}
    r = client.post("/card-purchases", json=corpo)
    assert r.status_code == 201
    assert (r.json()[0]["reference"], r.json()[0]["due_date"]) == ("2026-07", "2026-07-19")
    r = client.post("/card-purchases", json={**corpo, "installments": 2})
    assert r.status_code == 422 and "faturas" in r.json()["detail"]
