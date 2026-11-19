from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import StaticPool


class Base(DeclarativeBase):
    pass


def make_session_factory(url: str) -> sessionmaker:
    kwargs = {}
    if url in ("sqlite://", "sqlite:///:memory:"):
        # mesma conexão para toda a sessão em memória
        kwargs = {"poolclass": StaticPool, "connect_args": {"check_same_thread": False}}
    from salim import models  # noqa: F401  (registra as tabelas no metadata)

    engine = create_engine(url, **kwargs)
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)
