import pytest
from fastapi.testclient import TestClient

from salim.app import create_app
from salim.auth import AuthConfig, LoginLimiter, hash_password, make_session, read_session, verify_password
from conftest import new_factory

SEGREDO = "x" * 40


def cfg(**kw):
    base = dict(username="pedro", password_hash=hash_password("senha-forte-123"), secret_key=SEGREDO,
                api_token="tok-api-123", cookie_secure=False)
    return AuthConfig(**{**base, **kw})


# ---- primitivas
def test_hash_e_verificacao_de_senha():
    h = hash_password("abc")
    assert verify_password("abc", h) and not verify_password("abd", h)
    assert h != hash_password("abc")                                  # salt aleatório
    assert not verify_password("abc", "lixo") and not verify_password("abc", "")


def test_sessao_assinada_expira_e_nao_aceita_adulteracao():
    c = cfg()
    ck = make_session(c, now=1000)
    assert read_session(c, ck, now=1000 + 60) == "pedro"
    assert read_session(c, ck, now=1000 + c.session_days * 86400 + 1) is None
    usuario, _, resto = ck.partition(".")
    assert read_session(c, "x" + ck, now=1001) is None
    assert read_session(c, ck[:-2] + "aa", now=1001) is None
    assert read_session(cfg(secret_key="y" * 40), ck, now=1001) is None
    assert read_session(c, "", now=1) is None and read_session(c, "sem-ponto", now=1) is None


def test_limitador_trava_apos_falhas_e_destrava_com_o_tempo():
    t = [0.0]
    factory = new_factory()
    lim = LoginLimiter(factory, max_failures=3, lock_seconds=900, clock=lambda: t[0])
    for _ in range(3):
        assert not lim.locked()
        lim.failure()
    assert lim.locked()
    t[0] = 901
    assert not lim.locked()
    lim.failure(); lim.success()
    assert not lim.locked()
    factory.kw["bind"].dispose()


def test_config_pelo_ambiente_e_validacoes(monkeypatch):
    for k in ("SALIM_USER", "SALIM_PASSWORD_HASH", "SALIM_SECRET_KEY", "SALIM_API_TOKEN", "SALIM_AUTH_DISABLED"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(RuntimeError, match="SALIM_PASSWORD_HASH"):
        AuthConfig.from_env()                                         # falha fechada
    monkeypatch.setenv("SALIM_AUTH_DISABLED", "1")
    assert AuthConfig.from_env() is None
    monkeypatch.delenv("SALIM_AUTH_DISABLED")
    monkeypatch.setenv("SALIM_PASSWORD_HASH", hash_password("x"))
    with pytest.raises(RuntimeError, match="SALIM_SECRET_KEY"):
        AuthConfig.from_env()
    monkeypatch.setenv("SALIM_SECRET_KEY", "curta")
    with pytest.raises(RuntimeError, match="32"):
        AuthConfig.from_env()
    monkeypatch.setenv("SALIM_SECRET_KEY", SEGREDO)
    c = AuthConfig.from_env()
    assert c.username == "admin" and c.cookie_secure is True and c.api_token is None


def test_app_sem_configuracao_de_auth_nao_sobe(monkeypatch):
    for k in ("SALIM_PASSWORD_HASH", "SALIM_AUTH_DISABLED"):
        monkeypatch.delenv(k, raising=False)
    factory = new_factory()
    with pytest.raises(RuntimeError, match="SALIM_PASSWORD_HASH"):
        create_app(factory)
    factory.kw["bind"].dispose()


def test_telegram_com_token_exige_segredo_do_webhook(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.delenv("TELEGRAM_WEBHOOK_SECRET", raising=False)
    factory = new_factory()
    with pytest.raises(RuntimeError, match="TELEGRAM_WEBHOOK_SECRET"):
        create_app(factory)
    factory.kw["bind"].dispose()


# ---- app protegido
@pytest.fixture
def app_client():
    factory = new_factory()
    app = create_app(factory, auth=cfg(), telegram_sender=lambda *a: None, telegram_allowed_ids={1})
    with TestClient(app, follow_redirects=False) as c:
        yield c
    factory.kw["bind"].dispose()


def entrar(c, senha="senha-forte-123", usuario="pedro", next_="/ui/accounts"):
    return c.post("/login", data={"username": usuario, "password": senha, "next": next_})


def test_health_e_webhooks_ficam_abertos(app_client):
    assert app_client.get("/health").status_code == 200
    r = app_client.post("/telegram/webhook", json={"update_id": 1, "message": {"chat": {"id": 1}, "from": {"id": 1}, "text": "/ajuda"}})
    assert r.status_code == 200
    assert app_client.get("/login").status_code == 200


def test_sem_login_api_da_401_e_telas_redirecionam(app_client):
    assert app_client.get("/accounts").status_code == 401
    assert app_client.post("/transactions", json={}).status_code == 401
    assert app_client.get("/budget").status_code == 401
    r = app_client.get("/ui/accounts")
    assert r.status_code == 303 and r.headers["location"] == "/login?next=/ui/accounts"
    assert app_client.get("/").status_code == 303


def test_login_errado_nao_entra(app_client):
    r = entrar(app_client, senha="errada")
    assert r.status_code == 401 and "inválid" in r.text.lower() and "set-cookie" not in r.headers
    assert entrar(app_client, usuario="outro").status_code == 401
    assert app_client.get("/accounts").status_code == 401


def test_login_certo_abre_tudo_e_cookie_e_seguro(app_client):
    r = entrar(app_client)
    assert r.status_code == 303 and r.headers["location"] == "/ui/accounts"
    ck = r.headers["set-cookie"].lower()
    assert "httponly" in ck and "samesite=lax" in ck
    assert app_client.get("/accounts").status_code == 200
    assert app_client.get("/ui/payables").status_code == 200


def test_cookie_secure_quando_configurado():
    factory = new_factory()
    with TestClient(create_app(factory, auth=cfg(cookie_secure=True)), follow_redirects=False) as c:
        assert "secure" in entrar(c).headers["set-cookie"].lower()
    factory.kw["bind"].dispose()


def test_next_externo_e_ignorado(app_client):
    assert entrar(app_client, next_="//evil.com").headers["location"] == "/"
    assert entrar(app_client, next_="https://evil.com").headers["location"] == "/"


def test_logout_encerra_a_sessao(app_client):
    entrar(app_client)
    assert app_client.post("/logout").status_code == 303
    assert app_client.get("/accounts").status_code == 401


def test_token_de_api(app_client):
    assert app_client.get("/accounts", headers={"Authorization": "Bearer tok-api-123"}).status_code == 200
    assert app_client.get("/accounts", headers={"Authorization": "Bearer errado"}).status_code == 401
    assert app_client.get("/accounts", headers={"Authorization": "tok-api-123"}).status_code == 401


def test_token_de_api_desligado_quando_nao_configurado():
    factory = new_factory()
    with TestClient(create_app(factory, auth=cfg(api_token=None)), follow_redirects=False) as c:
        assert c.get("/accounts", headers={"Authorization": "Bearer "}).status_code == 401
    factory.kw["bind"].dispose()


def test_trava_apos_cinco_erros_mesmo_com_senha_certa(app_client):
    for _ in range(5):
        assert entrar(app_client, senha="errada").status_code == 401
    assert entrar(app_client).status_code == 429
    assert app_client.get("/accounts").status_code == 401


def test_tela_de_login_tem_formulario(app_client):
    html = app_client.get("/login?next=/ui/budget").text
    assert 'name="password"' in html and 'value="/ui/budget"' in html


def test_nav_mostra_sair_quando_logado(app_client):
    entrar(app_client)
    assert "Sair" in app_client.get("/ui/accounts").text
