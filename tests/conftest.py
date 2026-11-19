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
