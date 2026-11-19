"""M3: runner de migrações do Postgres (python -m salim.migrate)."""
import os
import textwrap

import pytest
from sqlalchemy import create_engine, text

from salim.migrate import apply_migrations, pending_versions

URL = os.environ.get("SALIM_TEST_DB_URL")
pytestmark = pytest.mark.skipif(not URL, reason="exige Postgres de teste (SALIM_TEST_DB_URL)")


# Esvazia o schema public sem exigir ser dono dele (no PG 15+ o dono é pg_database_owner).
LIMPA = """
DO $$ DECLARE r record; BEGIN
  FOR r IN SELECT viewname FROM pg_views WHERE schemaname = 'public' LOOP
    EXECUTE format('DROP VIEW IF EXISTS %I CASCADE', r.viewname); END LOOP;
  FOR r IN SELECT tablename FROM pg_tables WHERE schemaname = 'public' LOOP
    EXECUTE format('DROP TABLE IF EXISTS %I CASCADE', r.tablename); END LOOP;
  FOR r IN SELECT p.oid::regprocedure AS f FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
           WHERE n.nspname = 'public' LOOP
    EXECUTE format('DROP FUNCTION IF EXISTS %s CASCADE', r.f); END LOOP;
END $$"""


@pytest.fixture
def engine():
    eng = create_engine(URL)
    with eng.begin() as c:
        assert c.execute(text("select current_database()")).scalar_one().endswith("_test")
        c.execute(text(LIMPA))
    yield eng
    eng.dispose()


def _tabelas(eng):
    with eng.connect() as c:
        return set(c.execute(text("select tablename from pg_tables where schemaname='public'")).scalars())


def test_aplica_migracoes_num_banco_vazio_e_registra(engine):
    aplicadas = apply_migrations(engine)
    assert aplicadas == ["0001_initial"]
    assert {"accounts", "postings", "transactions", "obligations", "schema_migrations"} <= _tabelas(engine)
    with engine.connect() as c:
        assert c.execute(text("select version from schema_migrations")).scalars().all() == ["0001_initial"]


def test_segunda_execucao_nao_faz_nada(engine):
    apply_migrations(engine)
    assert apply_migrations(engine) == []
    assert pending_versions(engine) == []


def test_ordem_e_migracao_nova_so_aplica_a_nova(engine, tmp_path):
    (tmp_path / "0001_a.sql").write_text("CREATE TABLE a (id int);")
    assert apply_migrations(engine, tmp_path) == ["0001_a"]
    (tmp_path / "0003_c.sql").write_text("CREATE TABLE c (id int);")
    (tmp_path / "0002_b.sql").write_text("CREATE TABLE b (id int);")
    assert pending_versions(engine, tmp_path) == ["0002_b", "0003_c"]
    assert apply_migrations(engine, tmp_path) == ["0002_b", "0003_c"]


def test_migracao_com_erro_desfaz_tudo_e_nao_registra(engine, tmp_path):
    (tmp_path / "0001_a.sql").write_text("CREATE TABLE a (id int);")
    (tmp_path / "0002_ruim.sql").write_text(textwrap.dedent("""
        CREATE TABLE b (id int);
        INSERT INTO tabela_que_nao_existe VALUES (1);"""))
    with pytest.raises(Exception):
        apply_migrations(engine, tmp_path)
    assert "a" in _tabelas(engine) and "b" not in _tabelas(engine)
    with engine.connect() as c:
        assert c.execute(text("select version from schema_migrations")).scalars().all() == ["0001_a"]


def test_arquivo_sem_numero_na_frente_e_recusado(engine, tmp_path):
    (tmp_path / "rascunho.sql").write_text("SELECT 1;")
    with pytest.raises(ValueError):
        apply_migrations(engine, tmp_path)


def test_duas_execucoes_concorrentes_aplicam_uma_vez(engine, tmp_path):
    import threading
    (tmp_path / "0001_a.sql").write_text("CREATE TABLE a (id int); SELECT pg_sleep(0.5);")
    resultados, erros = [], []

    def roda():
        e = create_engine(URL)
        try:
            resultados.append(apply_migrations(e, tmp_path))
        except Exception as ex:  # noqa: BLE001
            erros.append(ex)
        finally:
            e.dispose()

    ts = [threading.Thread(target=roda) for _ in range(2)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not erros
    assert sorted(map(tuple, resultados)) == [(), ("0001_a",)]
