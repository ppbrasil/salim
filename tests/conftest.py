import pytest
from fastapi.testclient import TestClient

from salim.app import create_app
from salim.db import make_session_factory


@pytest.fixture
def session():
    """Banco SQLite em memória, schema limpo a cada teste."""
    factory = make_session_factory("sqlite://")
    with factory() as s:
        yield s
    factory.kw["bind"].dispose()


@pytest.fixture
def client():
    """App completo (plano padrão semeado) sobre banco em memória."""
    factory = make_session_factory("sqlite://")
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
