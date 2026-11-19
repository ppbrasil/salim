from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import StaticPool

SCHEMA = (Path(__file__).parent / "schema.sql").read_text()


class Base(DeclarativeBase):
    pass


def make_session_factory(url: str) -> sessionmaker:
    """Cria o engine e aplica schema.sql (fonte única: tabelas, triggers e views) se o banco for novo."""
    kwargs = {}
    if url in ("sqlite://", "sqlite:///:memory:"):
        kwargs = {"poolclass": StaticPool, "connect_args": {"check_same_thread": False}}
    engine = create_engine(url, **kwargs)

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
    from salim import models  # noqa: F401
    return sessionmaker(engine, expire_on_commit=False)
