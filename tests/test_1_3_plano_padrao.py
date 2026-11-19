from sqlalchemy import func, select

from salim.chart import seed_chart
from salim.ledger import get_account
from salim.models import Account, AccountType


def test_seed_cria_arvore_base(session):
    seed_chart(session)
    assert get_account(session, "5.01.01").name == "Aluguel"
    assert get_account(session, "5.01.01").type == AccountType.EXPENSE
    assert get_account(session, "5.01").is_group is True
    assert get_account(session, "5.01.01").parent_id == get_account(session, "5.01").id


def test_seed_tem_contas_temporarias_para_transicao_reembolso_e_divida(session):
    seed_chart(session)
    for code in ("1.03.01", "1.04.01", "2.03.01"):
        assert get_account(session, code).is_temporary is True


def test_seed_e_idempotente(session):
    seed_chart(session)
    n1 = session.execute(select(func.count()).select_from(Account)).scalar()
    seed_chart(session)
    n2 = session.execute(select(func.count()).select_from(Account)).scalar()
    assert n1 == n2 and n1 > 20
