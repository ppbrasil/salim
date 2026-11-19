from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from salim.chart import seed_chart
from salim.ledger import Entry, InvalidTransactionError, MissingObligationError, create_account, get_account, post_transaction
from salim.models import AccountType, Obligation, Posting, Transaction

D = date(2026, 7, 10)


def _cartao(session):
    seed_chart(session)
    create_account(session, code="2.01.01", name="Cartão", type=AccountType.LIABILITY, parent_code="2.01",
                   tracks_obligations=True, closing_day=25, due_day=5)
    tx = Transaction(event_date=D, description="abre fatura")
    session.add(tx); session.flush()
    obl = Obligation(account_id=get_account(session, "2.01.01").id, kind="invoice", due_date=date(2026, 8, 5),
                     closing_date=date(2026, 7, 25), reference="2026-07", created_by_tx_id=tx.id)
    session.add(obl); session.commit()
    return obl


def test_partida_aponta_para_titulo(session):
    obl = _cartao(session)
    tx = post_transaction(session, event_date=D, description="Mercado",
                          entries=[Entry("5.02.01", 60000), Entry("2.01.01", -60000, obligation_id=obl.id)])
    p = session.query(Posting).filter_by(transaction_id=tx.id, obligation_id=obl.id).one()
    assert p.amount_cents == -60000


def test_conta_com_titulo_exige_obligation_id(session):
    _cartao(session)
    with pytest.raises(MissingObligationError):
        post_transaction(session, event_date=D, description="x",
                         entries=[Entry("5.02.01", 100), Entry("2.01.01", -100)])
    assert session.query(Posting).count() == 0


def test_titulo_de_outra_conta_e_rejeitado(session):
    obl = _cartao(session)
    with pytest.raises(InvalidTransactionError):
        post_transaction(session, event_date=D, description="x",
                         entries=[Entry("5.02.01", 100), Entry("2.02.01", -100, obligation_id=obl.id)])
    assert session.query(Posting).count() == 0


def test_titulo_em_conta_comum_e_rejeitado(session):
    obl = _cartao(session)
    with pytest.raises(InvalidTransactionError):
        post_transaction(session, event_date=D, description="x",
                         entries=[Entry("5.02.01", 100, obligation_id=obl.id), Entry("1.01.01", -100)])


def test_banco_barra_mesmo_sem_passar_pelo_servico(session):
    obl = _cartao(session)
    tx = Transaction(event_date=D, description="burla"); session.add(tx); session.flush()
    with pytest.raises(IntegrityError, match="exige titulo"):
        session.execute(text("insert into postings (transaction_id, account_id, amount_cents, competence_month)"
                             " values (:t, :a, -1, '2026-07-01')"),
                        {"t": tx.id, "a": get_account(session, "2.01.01").id})
    session.rollback()
