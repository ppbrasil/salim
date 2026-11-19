from pathlib import Path

from sqlalchemy import BigInteger, cast, create_engine, event, func, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import StaticPool

SCHEMA = (Path(__file__).parent / "schema.sql").read_text()


class Base(DeclarativeBase):
    pass


def sum_cents(col):
    """SUM de centavos como inteiro. No Postgres SUM(BIGINT) é numeric (Decimal); o CAST mantém int nos dois bancos."""
    return cast(func.coalesce(func.sum(col), 0), BigInteger)


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


def make_engine(url: str):
    kwargs = {}
    if url in ("sqlite://", "sqlite:///:memory:"):
        kwargs = {"poolclass": StaticPool, "connect_args": {"check_same_thread": False}}
    return create_engine(url, **kwargs)


def make_session_factory(url: str) -> sessionmaker:
    """Cria o engine. SQLite: aplica schema.sql se o banco for novo. Postgres: o schema vem das migrações
    (`python -m salim.migrate`); a partida do app não altera o banco."""
    engine = make_engine(url)
    if engine.dialect.name == "sqlite":
        _prepare_sqlite(engine)
    from salim import models  # noqa: F401
    return sessionmaker(engine, expire_on_commit=False)
