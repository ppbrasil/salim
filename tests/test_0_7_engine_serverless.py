"""M7: engine do Postgres para serverless (Vercel + Neon)."""
import os

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool, QueuePool

from salim.db import connect_with_retry, make_engine, normalize_url, serverless_pg_config

NEON = "postgresql://u:p@ep-abc-123-pooler.sa-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"


def test_normaliza_a_url_do_neon_para_o_driver_psycopg():
    assert normalize_url(NEON).startswith("postgresql+psycopg://u:p@ep-abc")
    assert normalize_url("postgres://u:p@h/db").startswith("postgresql+psycopg://")
    assert normalize_url("postgresql+psycopg://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert normalize_url("sqlite:///x.db") == "sqlite:///x.db"


def test_serverless_usa_nullpool_e_nao_prepara_statements():
    e = make_engine(NEON, serverless=True)
    assert isinstance(e.pool, NullPool)
    assert e.dialect.name == "postgresql" and e.dialect.driver == "psycopg"
    _, kw = serverless_pg_config(make_url(NEON))
    assert kw == {"connect_timeout": 10, "prepare_threshold": None}


def test_fora_do_serverless_mantem_pool_normal():
    assert isinstance(make_engine("postgresql://u:p@localhost/db", serverless=False).pool, QueuePool)


def test_ssl_e_exigido_fora_da_maquina_local_mas_nao_no_localhost():
    remoto, _ = serverless_pg_config(make_url("postgresql+psycopg://u:p@ep-x.neon.tech/db"))
    assert remoto.query["sslmode"] == "require"
    local, _ = serverless_pg_config(make_url("postgresql+psycopg://u:p@127.0.0.1/db"))
    assert "sslmode" not in local.query
    explicito, _ = serverless_pg_config(make_url("postgresql+psycopg://u:p@h.neon.tech/db?sslmode=verify-full"))
    assert explicito.query["sslmode"] == "verify-full"


def test_serverless_e_detectado_pelo_ambiente_da_vercel(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    assert isinstance(make_engine("postgresql://u:p@h.neon.tech/db").pool, NullPool)
    monkeypatch.delenv("VERCEL")
    monkeypatch.setenv("SALIM_SERVERLESS", "1")
    assert isinstance(make_engine("postgresql://u:p@h.neon.tech/db").pool, NullPool)


def test_cold_start_tenta_de_novo_e_acaba_conectando():
    chamadas, esperas = [], []

    def conecta():
        chamadas.append(1)
        if len(chamadas) < 3:
            raise ConnectionError("banco acordando")
        return "conexao"

    assert connect_with_retry(conecta, attempts=4, delay=0.5, sleep=esperas.append) == "conexao"
    assert len(chamadas) == 3 and esperas == [0.5, 1.0]


def test_desiste_depois_do_limite_e_propaga_o_erro():
    def conecta():
        raise ConnectionError("fora do ar")

    esperas = []
    with pytest.raises(ConnectionError):
        connect_with_retry(conecta, attempts=3, delay=0.1, sleep=esperas.append)
    assert len(esperas) == 2


def test_default_factory_prefere_database_url(monkeypatch):
    from salim.app import _default_factory
    monkeypatch.setenv("DATABASE_URL", NEON)
    monkeypatch.setenv("SALIM_DB_URL", "sqlite://")
    sf = _default_factory()
    assert sf.kw["bind"].dialect.name == "postgresql"
    sf.kw["bind"].dispose()


@pytest.mark.skipif(not os.environ.get("SALIM_TEST_DB_URL"), reason="exige Postgres de teste")
def test_conecta_de_verdade_em_modo_serverless_e_reabre_a_cada_uso():
    e = make_engine(os.environ["SALIM_TEST_DB_URL"], serverless=True)
    for _ in range(3):
        with e.connect() as c:
            assert c.execute(text("select 1")).scalar_one() == 1
    assert e.pool.status() == "NullPool"
