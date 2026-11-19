import sqlite3
from datetime import datetime

import pytest

from salim.backup import backup_database, db_path_from_url
from salim.chart import seed_chart
from salim.db import make_session_factory
from salim.ledger import Entry, balance, post_transaction


@pytest.fixture
def banco(tmp_path):
    caminho = tmp_path / "salim.db"
    factory = make_session_factory(f"sqlite:///{caminho}")
    with factory() as s:
        seed_chart(s)
        post_transaction(s, event_date=datetime(2026, 8, 5).date(), description="Salário",
                         entries=[Entry("1.01.01", 500000), Entry("4.01", -500000)])
    factory.kw["bind"].dispose()
    return caminho


def test_url_do_banco_vira_caminho():
    assert str(db_path_from_url("sqlite:////data/salim.db")) == "/data/salim.db"
    assert str(db_path_from_url("sqlite:///data/salim.db")) == "data/salim.db"
    with pytest.raises(ValueError):
        db_path_from_url("sqlite://")
    with pytest.raises(ValueError):
        db_path_from_url("postgresql://x")


def test_backup_gera_copia_consistente_que_abre_e_tem_os_dados(banco, tmp_path):
    destino = tmp_path / "bk"
    arq = backup_database(banco, destino, now=datetime(2026, 11, 19, 3, 0, 0))
    assert arq.name == "salim-20261119-030000.db"
    factory = make_session_factory(f"sqlite:///{arq}")
    with factory() as s:
        assert balance(s, "1.01.01") == 500000
    factory.kw["bind"].dispose()


def test_backup_mantem_so_os_mais_recentes(banco, tmp_path):
    destino = tmp_path / "bk"
    for dia in range(1, 6):
        backup_database(banco, destino, keep=3, now=datetime(2026, 11, dia, 3, 0, 0))
    assert [p.name for p in sorted(destino.iterdir())] == [
        "salim-20261103-030000.db", "salim-20261104-030000.db", "salim-20261105-030000.db"]


def test_backup_de_banco_inexistente_falha_sem_criar_lixo(tmp_path):
    with pytest.raises(FileNotFoundError):
        backup_database(tmp_path / "nao-existe.db", tmp_path / "bk")
    assert not (tmp_path / "bk").exists() or list((tmp_path / "bk").iterdir()) == []


def test_backup_corrompido_nao_substitui_os_bons(banco, tmp_path):
    ruim = tmp_path / "ruim.db"
    ruim.write_bytes(b"isto nao e um sqlite")
    destino = tmp_path / "bk"
    bom = backup_database(banco, destino, now=datetime(2026, 11, 1, 3, 0, 0))
    with pytest.raises((sqlite3.DatabaseError, ValueError)):
        backup_database(ruim, destino, keep=1, now=datetime(2026, 11, 2, 3, 0, 0))
    assert bom.exists() and len(list(destino.iterdir())) == 1
