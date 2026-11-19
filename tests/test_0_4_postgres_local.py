"""M0 — Postgres de teste acessível (local, compose ou CI). Pulado quando SALIM_TEST_DB_URL não está definido."""
import os

import pytest
from sqlalchemy import create_engine, text

URL = os.environ.get("SALIM_TEST_DB_URL")
pytestmark = pytest.mark.skipif(not URL, reason="SALIM_TEST_DB_URL não definido")


@pytest.fixture
def conn():
    engine = create_engine(URL)
    with engine.connect() as c:
        yield c
    engine.dispose()


def test_url_usa_driver_psycopg():
    assert URL.startswith("postgresql+psycopg://")


def test_conecta_e_versao_minima(conn):
    assert conn.execute(text("select 1")).scalar_one() == 1
    assert conn.execute(text("show server_version_num")).scalar_one() is not None
    assert int(conn.execute(text("show server_version_num")).scalar_one()) >= 160000


def test_banco_de_teste_nao_e_o_de_producao(conn):
    """Trava de segurança: os testes truncam tabelas, então o banco precisa se chamar *_test."""
    assert conn.execute(text("select current_database()")).scalar_one().endswith("_test")
