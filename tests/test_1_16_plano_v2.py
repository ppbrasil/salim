from salim.chart import seed_chart
from salim.ledger import get_account


def test_flags_do_plano_padrao(session):
    seed_chart(session)
    assert get_account(session, "1.01.01").is_cash and get_account(session, "1.01.02").is_cash
    for code in ("1.03.01", "2.02.01", "2.03.01", "2.04.01"):
        assert get_account(session, code).tracks_obligations, code
    assert not get_account(session, "5.01.01").tracks_obligations


def test_juros_e_multas_sao_linhas_separadas(session):
    seed_chart(session)
    assert get_account(session, "5.07.01").name == "Juros"
    assert get_account(session, "5.07.02").name == "Multas"
    assert get_account(session, "5.07").is_group


def test_parcelamentos_e_renegociacoes_tem_conta_propria(session):
    seed_chart(session)
    assert get_account(session, "2.04.01").name == "Parcelamentos e Renegociações"
