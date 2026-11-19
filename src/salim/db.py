import os
import time
from pathlib import Path

from sqlalchemy import BigInteger, cast, create_engine, event, func, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import NullPool, StaticPool

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


def normalize_url(url: str) -> str:
    """postgres:// e postgresql:// (formato que Neon e Vercel entregam) -> driver psycopg 3."""
    for prefixo in ("postgres://", "postgresql://"):
        if url.startswith(prefixo):
            return "postgresql+psycopg://" + url.removeprefix(prefixo)
    return url


def connect_with_retry(connect, attempts: int = 4, delay: float = 0.5, sleep=time.sleep):
    """Cold start do Neon: o banco dorme após inatividade e a primeira conexão pode falhar. Tenta de novo, com espera crescente."""
    for n in range(1, attempts + 1):
        try:
            return connect()
        except Exception:
            if n == attempts:
                raise
            sleep(delay * n)


def _serverless(flag: bool | None) -> bool:
    return flag if flag is not None else bool(os.environ.get("VERCEL") or os.environ.get("SALIM_SERVERLESS"))


def serverless_pg_config(u):
    """URL e connect_args do Postgres em serverless: SSL obrigatório fora da máquina local, timeout curto, sem prepared statements."""
    if u.host not in (None, "localhost", "127.0.0.1", "::1") and "sslmode" not in u.query:
        u = u.update_query_dict({"sslmode": "require"})
    return u, {"connect_timeout": 10, "prepare_threshold": None}


def make_engine(url: str, serverless: bool | None = None):
    """SQLite (dev/testes) ou Postgres. No serverless: sem pool (cada invocação abre e fecha, o pooler do Neon
    é quem segura as conexões), SSL obrigatório fora da máquina local, sem prepared statements (PgBouncer)."""
    url = normalize_url(url)
    if url in ("sqlite://", "sqlite:///:memory:"):
        return create_engine(url, poolclass=StaticPool, connect_args={"check_same_thread": False})
    u = make_url(url)
    if u.get_backend_name() != "postgresql" or not _serverless(serverless):
        return create_engine(url)
    u, connect_args = serverless_pg_config(u)
    engine = create_engine(u, poolclass=NullPool, connect_args=connect_args)

    @event.listens_for(engine, "do_connect")
    def _retry(dialect, conn_rec, cargs, cparams):
        return connect_with_retry(lambda: dialect.loaded_dbapi.connect(*cargs, **cparams))

    return engine


def make_session_factory(url: str) -> sessionmaker:
    """Cria o engine. SQLite: aplica schema.sql se o banco for novo. Postgres: o schema vem das migrações
    (`python -m salim.migrate`); a partida do app não altera o banco."""
    engine = make_engine(url)
    if engine.dialect.name == "sqlite":
        _prepare_sqlite(engine)
    from salim import models  # noqa: F401
    return sessionmaker(engine, expire_on_commit=False)
