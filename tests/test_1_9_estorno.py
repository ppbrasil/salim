from datetime import date

import pytest

from salim.chart import seed_chart
from salim.ledger import (
    AlreadyReversedError, Entry, ImmutableError, balance, post_transaction, reverse_transaction,
)
from salim.models import Posting, Transaction


def _lanca(session):
    seed_chart(session)
    return post_transaction(
        session, event_date=date(2026, 11, 5), description="Aluguel",
        entries=[Entry("5.01.01", 300000, competence_date=date(2026, 11, 1)), Entry("1.01.01", -300000)],
    )


def test_estorno_zera_o_efeito_e_preserva_o_original(session):
    tx = _lanca(session)
    est = reverse_transaction(session, tx.id, event_date=date(2026, 11, 6))
    assert est.reverses_id == tx.id
    assert balance(session, "5.01.01") == 0
    assert balance(session, "1.01.01") == 0
    # original segue lá, intacto
    assert session.get(Transaction, tx.id).description == "Aluguel"
    assert session.query(Transaction).count() == 2


def test_estorno_preserva_competencia_da_partida(session):
    tx = _lanca(session)
    est = reverse_transaction(session, tx.id, event_date=date(2026, 11, 6))
    rows = session.query(Posting).filter_by(transaction_id=est.id).all()
    assert sorted(p.competence_date for p in rows) == [date(2026, 11, 1), date(2026, 11, 5)]  # espelha o original


def test_nao_estorna_duas_vezes(session):
    tx = _lanca(session)
    reverse_transaction(session, tx.id, event_date=date(2026, 11, 6))
    with pytest.raises(AlreadyReversedError):
        reverse_transaction(session, tx.id, event_date=date(2026, 11, 7))


def test_partida_e_imutavel(session):
    tx = _lanca(session)
    p = session.query(Posting).filter_by(transaction_id=tx.id).first()
    p.amount_cents = 1
    with pytest.raises(ImmutableError):
        session.commit()
    session.rollback()
