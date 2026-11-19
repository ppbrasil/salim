from datetime import date

import pytest
from sqlalchemy import func, select

from salim.chart import seed_chart
from salim.ledger import new_transaction
from salim.models import Obligation
from salim.obligations import ObligationError, create_obligation


def test_cria_titulo_com_vencimento(session):
    seed_chart(session)
    tx = new_transaction(session, event_date=date(2026, 10, 10), description="Conta de luz")
    obl = create_obligation(session, tx, account_code="2.02.01", kind="bill", due_date=date(2026, 10, 20),
                            reference="luz out", counterparty="Copel")
    session.commit()
    assert obl.id and obl.due_date == date(2026, 10, 20) and obl.created_by_tx_id == tx.id
    assert session.execute(select(func.count()).select_from(Obligation)).scalar() == 1


def test_conta_que_nao_controla_titulos_e_rejeitada(session):
    seed_chart(session)
    tx = new_transaction(session, event_date=date(2026, 10, 10), description="x")
    with pytest.raises(ObligationError):
        create_obligation(session, tx, account_code="5.01.01", kind="bill", due_date=date(2026, 10, 20))
    session.rollback()


def test_tipo_invalido_e_rejeitado(session):
    seed_chart(session)
    tx = new_transaction(session, event_date=date(2026, 10, 10), description="x")
    with pytest.raises(ObligationError):
        create_obligation(session, tx, account_code="2.02.01", kind="banana", due_date=date(2026, 10, 20))
    session.rollback()
