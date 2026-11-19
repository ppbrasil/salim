import pytest

from salim.ledger import DuplicateAccountError, create_account, get_account
from salim.models import AccountType


def test_cria_e_busca_conta_por_codigo(session):
    create_account(session, code="1.1.1", name="Conta Corrente", type=AccountType.ASSET)
    conta = get_account(session, "1.1.1")
    assert conta.name == "Conta Corrente"
    assert conta.type == AccountType.ASSET
    assert conta.is_group is False
    assert not conta.is_cash and not conta.tracks_obligations


def test_codigo_duplicado_falha(session):
    create_account(session, code="1.1.1", name="A", type=AccountType.ASSET)
    with pytest.raises(DuplicateAccountError):
        create_account(session, code="1.1.1", name="B", type=AccountType.ASSET)
