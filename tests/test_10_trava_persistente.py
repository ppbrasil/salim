"""M5: a trava de login vive no banco; vale para qualquer instância/processo."""
import pytest
from sqlalchemy import text

from conftest import new_factory
from salim.auth import LoginLimiter


@pytest.fixture
def sf():
    f = new_factory()
    yield f
    f.kw["bind"].dispose()


def limiter(sf, t, **kw):
    return LoginLimiter(sf, max_failures=3, lock_seconds=900, clock=lambda: t[0], **kw)


def test_falhas_contam_entre_instancias(sf):
    t = [1000.0]
    for _ in range(2):
        limiter(sf, t).failure()                   # cada falha chega a um processo diferente
    assert not limiter(sf, t).locked()
    limiter(sf, t).failure()
    assert limiter(sf, t).locked()                 # a terceira trava para todos


def test_trava_expira_e_zera_a_contagem(sf):
    t = [1000.0]
    for _ in range(3):
        limiter(sf, t).failure()
    t[0] = 1000 + 899
    assert limiter(sf, t).locked()
    t[0] = 1000 + 901
    assert not limiter(sf, t).locked()
    limiter(sf, t).failure(); limiter(sf, t).failure()
    assert not limiter(sf, t).locked()             # recomeçou do zero: 2 falhas, não 5


def test_sucesso_zera(sf):
    t = [1000.0]
    limiter(sf, t).failure(); limiter(sf, t).failure()
    limiter(sf, t).success()
    limiter(sf, t).failure(); limiter(sf, t).failure()
    assert not limiter(sf, t).locked()


def test_nao_guarda_senha_nem_ip_so_contagem(sf):
    t = [1000.0]
    limiter(sf, t).failure()
    with sf() as s:
        cols = [r[0] for r in s.execute(text("select * from login_throttle")).cursor.description]
    assert set(cols) == {"key", "failures", "locked_until"}
