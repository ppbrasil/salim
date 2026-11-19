import pytest

from salim.ledger import InvalidAccountError, create_account, get_account
from salim.models import AccountType


def test_flags_persistem(session):
    create_account(session, code="1.01.01", name="Banco", type=AccountType.ASSET, is_cash=True)
    create_account(session, code="2.01.01", name="Cartão", type=AccountType.LIABILITY,
                   tracks_obligations=True, closing_day=25, due_day=5)
    assert get_account(session, "1.01.01").is_cash is True
    c = get_account(session, "2.01.01")
    assert (c.tracks_obligations, c.closing_day, c.due_day) == (True, 25, 5)


def test_grupo_nao_pode_ser_caixa_nem_ter_titulo(session):
    with pytest.raises(InvalidAccountError):
        create_account(session, code="1", name="G", type=AccountType.ASSET, is_group=True, is_cash=True)
    with pytest.raises(InvalidAccountError):
        create_account(session, code="2", name="G", type=AccountType.LIABILITY, is_group=True, tracks_obligations=True)


def test_dia_de_fechamento_invalido(session):
    with pytest.raises(InvalidAccountError):
        create_account(session, code="2.01.01", name="Cartão", type=AccountType.LIABILITY,
                       tracks_obligations=True, closing_day=40, due_day=5)
