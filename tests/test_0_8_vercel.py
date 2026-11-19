"""M8: entrada da Vercel (api/index.py) e vercel.json."""
import importlib.util
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

RAIZ = Path(__file__).resolve().parent.parent


@pytest.fixture
def entrada(monkeypatch):
    monkeypatch.setenv("SALIM_DB_URL", "sqlite://")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("SALIM_AUTH_DISABLED", "1")
    spec = importlib.util.spec_from_file_location("vercel_entrada", RAIZ / "api" / "index.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    yield mod
    sys.modules.pop("vercel_entrada", None)


def test_entrada_expoe_app_asgi_e_responde_health(entrada):
    with TestClient(entrada.app) as c:
        assert c.get("/health").status_code == 200


def test_partida_serverless_nao_escreve_no_banco(entrada):
    from salim.models import Account
    sf = entrada.app.state.sf
    with sf() as s:
        assert s.query(Account).count() == 0


def test_vercel_json_manda_tudo_para_a_funcao_e_empacota_templates_e_sql():
    cfg = json.loads((RAIZ / "vercel.json").read_text())
    assert {"source": "/(.*)", "destination": "/api/index"} in cfg["rewrites"]
    fn = cfg["functions"]["api/index.py"]
    assert "src/**" in fn["includeFiles"]
    assert cfg["regions"] == ["gru1"]


def test_dependencias_de_producao_incluem_o_driver_do_postgres():
    import tomllib
    deps = tomllib.loads((RAIZ / "pyproject.toml").read_text())["project"]["dependencies"]
    assert "psycopg[binary]" in deps and "fastapi" in deps and "tzdata" in deps


def test_templates_e_migracoes_existem_no_pacote():
    assert list((RAIZ / "src/salim/migrations").glob("0*.sql"))
    assert list((RAIZ / "src/salim/templates").glob("*.html"))
