import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from salim.app import create_app
from salim.db import make_session_factory

# A suíte roda sem login; os testes de autenticação passam `auth=` explicitamente.
os.environ.setdefault("SALIM_AUTH_DISABLED", "1")

# Com SALIM_TEST_DB_URL a suíte roda no Postgres; sem ela, em SQLite na memória.
TEST_URL = os.environ.get("SALIM_TEST_DB_URL")


def new_factory():
    """Fábrica de sessões limpa. SQLite: banco novo em memória. Postgres: schema aplicado uma vez
    e TRUNCATE de todas as tabelas entre os testes (TRUNCATE não dispara os triggers de imutabilidade)."""
    if not TEST_URL:
        return make_session_factory("sqlite://")
    factory = make_session_factory(TEST_URL)
    with factory.kw["bind"].begin() as c:
        nome = c.execute(text("select current_database()")).scalar_one()
        assert nome.endswith("_test"), f"recusando truncar o banco {nome!r}: a suíte só roda em bancos *_test"
        tabelas = c.execute(text(
            "select tablename from pg_tables where schemaname = 'public' and tablename <> 'schema_migrations'")).scalars().all()
        if tabelas:
            c.execute(text("TRUNCATE " + ", ".join(f'"{t}"' for t in tabelas) + " RESTART IDENTITY CASCADE"))
    return factory


@pytest.fixture
def session():
    """Banco limpo a cada teste (SQLite em memória ou Postgres de teste)."""
    factory = new_factory()
    with factory() as s:
        yield s
    factory.kw["bind"].dispose()


@pytest.fixture
def client():
    """App completo (plano padrão semeado) sobre banco limpo."""
    factory = new_factory()
    with TestClient(create_app(factory)) as c:
        yield c
    factory.kw["bind"].dispose()


class _Ctx:
    """Entrega a sessão do teste como context manager, sem fechá-la."""
    def __init__(self, s): self.s = s
    def __enter__(self): return self.s
    def __exit__(self, *a): return False


@pytest.fixture
def ctx_factory(session):
    return lambda: _Ctx(session)
