"""Backup consistente do SQLite (API de backup, seguro com o app rodando) com retenção.

  python -m salim.backup                 # um backup agora
  python -m salim.backup --loop 24       # um por dia, para sempre (serviço `backup` do compose)
"""
import os
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path


def db_path_from_url(url: str) -> Path:
    if not url.startswith("sqlite:///") or url == "sqlite://" or url.endswith(":memory:"):
        raise ValueError(f"backup só funciona com SQLite em arquivo (recebi {url!r})")
    return Path(url[len("sqlite:///"):])


def backup_database(origem: Path, destino: Path, keep: int = 14, now: datetime | None = None) -> Path:
    origem, destino = Path(origem), Path(destino)
    if not origem.exists():
        raise FileNotFoundError(origem)
    destino.mkdir(parents=True, exist_ok=True)
    arq = destino / f"salim-{(now or datetime.now()):%Y%m%d-%H%M%S}.db"
    tmp = arq.with_suffix(".tmp")
    src = sqlite3.connect(f"file:{origem}?mode=ro", uri=True)
    dst = sqlite3.connect(tmp)
    try:
        src.backup(dst)
        if dst.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("backup não passou na verificação de integridade")
    except Exception:
        dst.close(); src.close()
        tmp.unlink(missing_ok=True)
        raise
    dst.close(); src.close()
    tmp.replace(arq)
    for velho in sorted(destino.glob("salim-*.db"))[:-keep]:
        velho.unlink()
    return arq


def main() -> None:
    origem = db_path_from_url(os.environ.get("SALIM_DB_URL", "sqlite:///data/salim.db"))
    destino = Path(os.environ.get("SALIM_BACKUP_DIR", str(origem.parent / "backups")))
    keep = int(os.environ.get("SALIM_BACKUP_KEEP", "14"))
    horas = float(sys.argv[sys.argv.index("--loop") + 1]) if "--loop" in sys.argv else None
    while True:
        try:
            print("backup:", backup_database(origem, destino, keep), flush=True)
        except Exception as e:  # o serviço continua tentando no próximo ciclo
            print("backup FALHOU:", e, file=sys.stderr, flush=True)
            if horas is None:
                raise
        if horas is None:
            return
        time.sleep(horas * 3600)


if __name__ == "__main__":
    main()
