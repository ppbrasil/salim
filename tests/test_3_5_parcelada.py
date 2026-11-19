from datetime import date

from sqlalchemy import select

from salim.chart import seed_chart
from salim.ledger import balance, create_account
from salim.models import AccountType, Obligation, Posting
from salim.obligations import list_obligations, register_card_purchase


def _cartao(session):
    seed_chart(session)
    create_account(session, code="2.01.01", name="Nubank", type=AccountType.LIABILITY, parent_code="2.01",
                   tracks_obligations=True, closing_day=25, due_day=5)


def test_tres_vezes_competencia_cheia_e_tres_faturas(session):
    _cartao(session)
    faturas = register_card_purchase(session, card_code="2.01.01", event_date=date(2026, 10, 10),
                                     description="TV", items=[("5.99", 30000)], installments=3)
    assert [(f.reference, f.due_date) for f in faturas] == [
        ("2026-10", date(2026, 11, 5)), ("2026-11", date(2026, 12, 5)), ("2026-12", date(2027, 1, 5))]
    comp = session.execute(select(Posting.competence_month, Posting.amount_cents)
                           .join(Obligation, Obligation.id == Posting.obligation_id, isouter=True)
                           .where(Posting.obligation_id.is_(None))).all()
    assert comp == [(date(2026, 10, 1), 30000)]                       # despesa inteira em outubro
    cred = sorted(session.execute(select(Posting.amount_cents).where(Posting.obligation_id.is_not(None))).scalars())
    assert cred == [-10000, -10000, -10000]


def test_resto_da_divisao_vai_para_a_primeira_parcela(session):
    _cartao(session)
    register_card_purchase(session, card_code="2.01.01", event_date=date(2026, 10, 10),
                           description="x", items=[("5.99", 10001)], installments=3)
    vistas = list_obligations(session, today=date(2026, 10, 11))
    assert [v.balance_cents for v in vistas] == [3335, 3333, 3333]
    assert sum(v.balance_cents for v in vistas) == 10001
    assert balance(session, "5.99") == 10001


def test_parcelas_atravessando_virada_de_ano(session):
    _cartao(session)
    faturas = register_card_purchase(session, card_code="2.01.01", event_date=date(2026, 11, 28),
                                     description="x", items=[("5.99", 3000)], installments=3)
    assert [f.reference for f in faturas] == ["2026-12", "2027-01", "2027-02"]
