from sqlalchemy import text

from salim.db import make_session_factory


def test_sessao_funciona(session):
    assert session.execute(text("select 1")).scalar() == 1


def test_bancos_em_memoria_sao_isolados():
    a = make_session_factory("sqlite://")
    b = make_session_factory("sqlite://")
    with a() as sa, b() as sb:
        sa.execute(text("create table t (x int)"))
        sa.commit()
        tabelas_b = sb.execute(text("select name from sqlite_master where name='t'")).all()
    a.kw["bind"].dispose()
    b.kw["bind"].dispose()
    assert tabelas_b == []
