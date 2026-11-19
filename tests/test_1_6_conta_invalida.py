from datetime import date

import pytest

from salim.chart import seed_chart
from salim.ledger import AccountNotFoundError, Entry, InvalidTransactionError, post_transaction
from salim.models import Posting, Transaction

D = date(2026, 11, 5)


def test_conta_inexistente_rejeita_e_nao_grava_nada(session):
    seed_chart(session)
    with pytest.raises(AccountNotFoundError):
        post_transaction(session, event_date=D, description="x",
                         entries=[Entry("5.99", 1000), Entry("9.9.9", -1000)])
    assert session.query(Transaction).count() == 0
    assert session.query(Posting).count() == 0


def test_conta_grupo_nao_recebe_lancamento(session):
    seed_chart(session)
    with pytest.raises(InvalidTransactionError):
        post_transaction(session, event_date=D, description="x",
                         entries=[Entry("5.01", 1000), Entry("1.01.01", -1000)])  # 5.01 é grupo
    assert session.query(Transaction).count() == 0
    assert session.query(Posting).count() == 0
