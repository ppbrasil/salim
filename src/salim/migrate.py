"""Migrações do Postgres: arquivos NNNN_nome.sql em salim/migrations, aplicados em ordem, uma transação cada.

    python -m salim.migrate            # aplica o que falta (DATABASE_URL ou SALIM_DB_URL)
    python -m salim.migrate --seed     # idem, e cria o plano de contas padrão se o banco estiver vazio

Seguro com execuções simultâneas: cada migração toma um lock consultivo e confere de novo se já foi aplicada.
"""
import os
import re
import sys
from pathlib import Path

from sqlalchemy import text

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_NOME = re.compile(r"^\d{4}_[a-z0-9_]+\.sql$")
_LOCK_ID = 727_274_001  # arbitrário, fixo: "salim migrations"

_CRIA_CONTROLE = """CREATE TABLE IF NOT EXISTS schema_migrations (
    version    TEXT PRIMARY KEY,
    applied_at TIMESTAMP NOT NULL DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC'))"""


def _arquivos(directory: Path | None) -> list[Path]:
    d = Path(directory) if directory else MIGRATIONS_DIR
    arqs = sorted(d.glob("*.sql"))
    for a in arqs:
        if not _NOME.match(a.name):
            raise ValueError(f"nome de migração inválido: {a.name} (use NNNN_descricao.sql)")
    return arqs


def _aplicadas(conn) -> set[str]:
    conn.execute(text(_CRIA_CONTROLE))
    return set(conn.execute(text("select version from schema_migrations")).scalars())


def pending_versions(engine, directory: Path | None = None) -> list[str]:
    arqs = _arquivos(directory)
    with engine.begin() as conn:
        feitas = _aplicadas(conn)
    return [a.stem for a in arqs if a.stem not in feitas]


def apply_migrations(engine, directory: Path | None = None) -> list[str]:
    """Aplica as migrações pendentes e devolve as versões aplicadas nesta chamada."""
    novas = []
    for arq in _arquivos(directory):
        with engine.begin() as conn:
            conn.execute(text("select pg_advisory_xact_lock(:k)"), {"k": _LOCK_ID})
            if arq.stem in _aplicadas(conn):
                continue
            conn.exec_driver_sql(arq.read_text())
            conn.execute(text("insert into schema_migrations (version) values (:v)"), {"v": arq.stem})
        novas.append(arq.stem)
    return novas


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    from salim.db import make_engine
    url = os.environ.get("DATABASE_URL") or os.environ.get("SALIM_DB_URL")
    if not url:
        print("defina DATABASE_URL (ou SALIM_DB_URL)", file=sys.stderr)
        return 2
    engine = make_engine(url)
    if engine.dialect.name != "postgresql":
        print("migrações só existem para Postgres (o SQLite cria o schema sozinho até o corte da M10)", file=sys.stderr)
        return 2
    feitas = apply_migrations(engine)
    print("aplicadas:", ", ".join(feitas) if feitas else "nada a fazer")
    if "--seed" in args:
        from sqlalchemy.orm import sessionmaker
        from salim.chart import seed_chart
        from salim.models import Account
        with sessionmaker(engine, expire_on_commit=False)() as s:
            if s.query(Account).first() is None:
                seed_chart(s)
                print("plano de contas padrão criado")
            else:
                print("plano de contas já existe")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
