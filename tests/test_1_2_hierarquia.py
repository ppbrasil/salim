import pytest

from salim.ledger import AccountNotFoundError, account_tree, create_account, get_account
from salim.models import AccountType


def test_filha_aponta_para_pai(session):
    create_account(session, code="1", name="Ativo", type=AccountType.ASSET, is_group=True)
    create_account(session, code="1.1", name="Caixa", type=AccountType.ASSET, parent_code="1")
    assert get_account(session, "1.1").parent_id == get_account(session, "1").id


def test_pai_inexistente_falha(session):
    with pytest.raises(AccountNotFoundError):
        create_account(session, code="9.1", name="X", type=AccountType.ASSET, parent_code="9")


def test_arvore_em_ordem_com_profundidade(session):
    create_account(session, code="1", name="Ativo", type=AccountType.ASSET, is_group=True)
    create_account(session, code="2", name="Passivo", type=AccountType.LIABILITY, is_group=True)
    create_account(session, code="1.1", name="Caixa", type=AccountType.ASSET, parent_code="1")
    create_account(session, code="1.2", name="Banco", type=AccountType.ASSET, parent_code="1")
    arvore = [(depth, a.code) for depth, a in account_tree(session)]
    assert arvore == [(0, "1"), (1, "1.1"), (1, "1.2"), (0, "2")]
