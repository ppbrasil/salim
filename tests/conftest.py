import pytest

from salim.db import make_session_factory


@pytest.fixture
def session():
    """Banco SQLite em memória, schema limpo a cada teste."""
    factory = make_session_factory("sqlite://")
    with factory() as s:
        yield s
    factory.kw["bind"].dispose()
