from datetime import date

import pytest
from sqlalchemy import func, select

from salim.chart import seed_chart
from salim.ledger import balance, create_account
from salim.models import AccountType, Obligation
from salim.obligations import ObligationError, get_obligation, list_obligations, register_card_purchase


def _cartao(session, closing=25, due=5, code="2.01.01"):
    seed_chart(session)
    create_account(session, code=code, name="Nubank", type=AccountType.LIABILITY, parent_code="2.01",
                   tracks_obligations=True, closing_day=closing, due_day=due)


def _faturas(session):
    return session.execute(select(Obligation).where(Obligation.kind == "invoice")
                           .order_by(Obligation.closing_date)).scalars().all()


def test_compra_abre_a_fatura_certa_sozinha(session):
    _cartao(session)
    [inv] = register_card_purchase(session, card_code="2.01.01", event_date=date(2026, 6, 28),
                                   description="Mercado", items=[("5.02.01", 60000)])
    assert (inv.closing_date, inv.due_date, inv.reference) == (date(2026, 7, 25), date(2026, 8, 5), "2026-07")
    v = get_obligation(session, inv.id, today=date(2026, 7, 1))
    assert (v.status, v.balance_cents) == ("aberta", 60000)


def test_segunda_compra_no_mesmo_periodo_reusa_a_fatura(session):
    _cartao(session)
    register_card_purchase(session, card_code="2.01.01", event_date=date(2026, 6, 28), description="a", items=[("5.02.01", 60000)])
    register_card_purchase(session, card_code="2.01.01", event_date=date(2026, 7, 10), description="b", items=[("5.02.02", 40000)])
    assert len(_faturas(session)) == 1
    assert balance(session, "2.01.01") == 100000


def test_dia_do_fechamento_ainda_entra_na_fatura_e_o_dia_seguinte_nao(session):
    _cartao(session)
    [a] = register_card_purchase(session, card_code="2.01.01", event_date=date(2026, 7, 25), description="a", items=[("5.99", 100)])
    [b] = register_card_purchase(session, card_code="2.01.01", event_date=date(2026, 7, 26), description="b", items=[("5.99", 100)])
    assert a.closing_date == date(2026, 7, 25) and b.closing_date == date(2026, 8, 25)
    assert b.due_date == date(2026, 9, 5)


def test_vencimento_no_mesmo_mes_quando_dia_de_vencimento_vem_depois_do_fechamento(session):
    _cartao(session, closing=5, due=15)
    [inv] = register_card_purchase(session, card_code="2.01.01", event_date=date(2026, 7, 1), description="a", items=[("5.99", 100)])
    assert (inv.closing_date, inv.due_date) == (date(2026, 7, 5), date(2026, 7, 15))


def test_fechamento_dia_31_ajusta_para_fim_do_mes(session):
    _cartao(session, closing=31, due=10)
    [inv] = register_card_purchase(session, card_code="2.01.01", event_date=date(2026, 2, 10), description="a", items=[("5.99", 100)])
    assert inv.closing_date == date(2026, 2, 28)


def test_varios_itens_viram_varias_despesas_e_um_credito_na_fatura(session):
    _cartao(session)
    register_card_purchase(session, card_code="2.01.01", event_date=date(2026, 7, 10), description="Compras",
                           items=[("5.02.01", 30000), ("5.04.01", 12000)])
    assert balance(session, "5.02.01") == 30000 and balance(session, "5.04.01") == 12000
    assert balance(session, "2.01.01") == 42000


def test_cartao_sem_dia_de_fechamento_e_rejeitado(session):
    seed_chart(session)
    create_account(session, code="2.01.02", name="Sem dias", type=AccountType.LIABILITY, parent_code="2.01",
                   tracks_obligations=True)
    with pytest.raises(ObligationError, match="fechamento"):
        register_card_purchase(session, card_code="2.01.02", event_date=date(2026, 7, 10), description="a", items=[("5.99", 100)])
    assert session.execute(select(func.count()).select_from(Obligation)).scalar() == 0
