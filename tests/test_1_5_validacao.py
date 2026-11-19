from datetime import date

import pytest

from salim.chart import seed_chart
from salim.ledger import Entry, InvalidTransactionError, UnbalancedTransactionError, post_transaction
from salim.models import Posting, Transaction

D = date(2026, 11, 5)


def _nada_gravado(session):
    assert session.query(Transaction).count() == 0
    assert session.query(Posting).count() == 0


def test_soma_diferente_de_zero_e_rejeitada(session):
    seed_chart(session)
    with pytest.raises(UnbalancedTransactionError):
        post_transaction(session, event_date=D, description="x",
                         entries=[Entry("5.99", 1000), Entry("1.01.01", -900)])
    _nada_gravado(session)


def test_menos_de_duas_partidas_e_rejeitada(session):
    seed_chart(session)
    with pytest.raises(InvalidTransactionError):
        post_transaction(session, event_date=D, description="x", entries=[Entry("5.99", 0)])
    _nada_gravado(session)


def test_partida_com_valor_zero_e_rejeitada(session):
    seed_chart(session)
    with pytest.raises(InvalidTransactionError):
        post_transaction(session, event_date=D, description="x",
                         entries=[Entry("5.99", 1000), Entry("1.01.01", -1000), Entry("5.02.01", 0)])
    _nada_gravado(session)
