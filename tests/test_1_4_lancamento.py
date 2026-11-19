from datetime import date

from salim.chart import seed_chart
from salim.ledger import Entry, get_account, post_transaction
from salim.models import Posting, Transaction


def test_lanca_despesa_com_duas_partidas(session):
    seed_chart(session)
    tx = post_transaction(
        session,
        event_date=date(2026, 11, 5),
        description="Aluguel de novembro",
        entries=[Entry("5.01.01", 300000), Entry("1.01.01", -300000)],
    )
    assert tx.id is not None
    partidas = session.query(Posting).filter_by(transaction_id=tx.id).all()
    assert len(partidas) == 2
    assert sum(p.amount_cents for p in partidas) == 0
    por_conta = {p.account_id: p.amount_cents for p in partidas}
    assert por_conta[get_account(session, "5.01.01").id] == 300000
    assert por_conta[get_account(session, "1.01.01").id] == -300000


def test_lancamento_com_tres_partidas(session):
    seed_chart(session)
    tx = post_transaction(
        session,
        event_date=date(2026, 11, 5),
        description="Mercado dividido",
        entries=[Entry("5.02.01", 8000), Entry("5.99", 2000), Entry("1.01.01", -10000)],
    )
    assert session.query(Posting).filter_by(transaction_id=tx.id).count() == 3
    assert session.query(Transaction).count() == 1
