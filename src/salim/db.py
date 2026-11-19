from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import StaticPool

SCHEMA = (Path(__file__).parent / "schema.sql").read_text()
SCHEMA_PG = (Path(__file__).parent / "schema_pg.sql").read_text()


class Base(DeclarativeBase):
    pass


def _prepare_sqlite(engine) -> None:
    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys = ON")

    with engine.begin() as conn:
        existe = conn.execute(text("select 1 from sqlite_master where name='accounts'")).first()
    if not existe:
        raw = engine.raw_connection()
        try:
            raw.executescript(SCHEMA)
            raw.commit()
        finally:
            raw.close()


def _prepare_postgres(engine) -> None:
    """Aplica schema_pg.sql (numa transação só) se o banco ainda não tem a tabela de contas.
    Provisório: na M3 isto sai da partida do app e vira migração."""
    with engine.begin() as conn:
        if conn.execute(text("select to_regclass('public.accounts')")).scalar_one() is None:
            conn.exec_driver_sql(SCHEMA_PG)


def make_session_factory(url: str) -> sessionmaker:
    """Cria o engine e aplica o schema do dialeto (fonte única: tabelas, triggers e views) se o banco for novo."""
    kwargs = {}
    if url in ("sqlite://", "sqlite:///:memory:"):
        kwargs = {"poolclass": StaticPool, "connect_args": {"check_same_thread": False}}
    engine = create_engine(url, **kwargs)
    (_prepare_sqlite if engine.dialect.name == "sqlite" else _prepare_postgres)(engine)
    from salim import models  # noqa: F401
    return sessionmaker(engine, expire_on_commit=False)
