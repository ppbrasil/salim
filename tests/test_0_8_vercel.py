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
    assert {"source": "/:path*", "destination": "/api/index?__p=:path*"} in cfg["rewrites"]
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


# --- a Vercel entrega ao app o caminho "/api/index"; o original vem na query (__p) ---

def _chamar(app_asgi, path, query):
    """Chama o ASGI direto e devolve (path, raw_path, query_string) vistos pelo app interno."""
    import asyncio
    visto = {}

    async def interno(scope, receive, send):
        visto.update(path=scope["path"], raw_path=scope["raw_path"], query=scope["query_string"].decode())

    from salim.vercel_path import RestaurarCaminhoOriginal
    envelope = RestaurarCaminhoOriginal(interno)
    scope = {"type": "http", "path": path, "raw_path": path.encode(), "query_string": query.encode()}
    asyncio.run(envelope(scope, None, None))
    return visto


def test_restaura_caminho_original_a_partir_da_query():
    v = _chamar(None, "/api/index", "__p=ui%2Fcontas&mes=2026-11")
    assert v["path"] == "/ui/contas" and v["raw_path"] == b"/ui/contas"
    assert v["query"] == "mes=2026-11"


def test_raiz_vira_barra():
    assert _chamar(None, "/api/index", "__p=")["path"] == "/"


def test_sem_parametro_nao_mexe_no_scope():
    v = _chamar(None, "/health", "x=1")
    assert v["path"] == "/health" and v["query"] == "x=1"


def test_ignora_eventos_que_nao_sao_http():
    import asyncio
    from salim.vercel_path import RestaurarCaminhoOriginal
    chamado = []

    async def interno(scope, receive, send):
        chamado.append(scope["type"])

    asyncio.run(RestaurarCaminhoOriginal(interno)({"type": "lifespan"}, None, None))
    assert chamado == ["lifespan"]


def test_entrada_atras_do_rewrite_serve_login_e_health_publicos(entrada, monkeypatch):
    """Simula o que a Vercel faz: tudo chega em /api/index com o caminho real em __p."""
    with TestClient(entrada.app) as c:
        assert c.get("/api/index", params={"__p": "health"}).status_code == 200
        assert c.get("/api/index", params={"__p": "login", "next": "/"}).status_code == 200


def test_entrada_mantem_state_do_app_interno(entrada):
    assert hasattr(entrada.app.state, "sf")


@pytest.fixture
def entrada_com_login(monkeypatch):
    from salim.auth import hash_password
    monkeypatch.setenv("SALIM_DB_URL", "sqlite://")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("SALIM_AUTH_DISABLED", raising=False)
    monkeypatch.setenv("SALIM_PASSWORD_HASH", hash_password("senha-de-teste-123"))
    monkeypatch.setenv("SALIM_SECRET_KEY", "x" * 40)
    spec = importlib.util.spec_from_file_location("vercel_entrada2", RAIZ / "api" / "index.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    yield mod
    sys.modules.pop("vercel_entrada2", None)


def test_com_login_ligado_atras_do_rewrite_paginas_abertas_e_protegidas(entrada_com_login):
    with TestClient(entrada_com_login.app, follow_redirects=False) as c:
        assert c.get("/api/index", params={"__p": "health"}).status_code == 200
        assert c.get("/api/index", params={"__p": "login"}).status_code == 200
        r = c.get("/api/index", params={"__p": ""})  # "/"
        assert r.status_code == 303 and r.headers["location"].startswith("/login")
        assert c.get("/api/index", params={"__p": "api/contas"}).status_code == 401
