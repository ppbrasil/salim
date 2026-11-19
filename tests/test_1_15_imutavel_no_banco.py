from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from salim.chart import seed_chart
from salim.ledger import Entry, post_transaction
from salim.models import Obligation


def _tx(session):
    seed_chart(session)
    return post_transaction(session, event_date=date(2026, 11, 5), description="x",
                            entries=[Entry("5.99", 100), Entry("1.01.01", -100)])


@pytest.mark.parametrize("sql", [
    "update postings set amount_cents = 1",
    "delete from postings",
    "update transactions set description = 'y'",
    "delete from transactions",
])
def test_sql_direto_em_lancamento_e_partida_falha(session, sql):
    _tx(session)
    with pytest.raises(IntegrityError, match="imutavel"):
        session.execute(text(sql))
    session.rollback()


def test_titulo_so_muda_vencimento_e_data_planejada(session):
    tx = _tx(session)
    session.execute(text("insert into obligations (account_id, kind, due_date, created_by_tx_id)"
                         " values (1, 'bill', '2026-12-01', :t)"), {"t": tx.id})
    session.commit()
    session.execute(text("update obligations set due_date='2026-12-10', planned_date='2026-12-08'"))
    session.commit()
    with pytest.raises(IntegrityError, match="imutaveis"):
        session.execute(text("update obligations set account_id = 2"))
    session.rollback()
    with pytest.raises(IntegrityError, match="nao se apaga"):
        session.execute(text("delete from obligations"))
    session.rollback()
