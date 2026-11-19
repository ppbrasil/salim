import pytest
from fastapi.testclient import TestClient

from salim.app import create_app
from conftest import new_factory

DONO = 111


@pytest.fixture
def tg():
    factory = new_factory()
    enviadas = []
    app = create_app(factory, telegram_sender=lambda chat, texto: enviadas.append((chat, texto)),
                     telegram_allowed_ids={DONO}, telegram_secret="s3gredo")
    with TestClient(app) as c:
        yield c, enviadas
    factory.kw["bind"].dispose()


def update(texto, uid=1, chat=DONO):
    return {"update_id": uid, "message": {"chat": {"id": chat}, "from": {"id": chat}, "text": texto}}


H = {"X-Telegram-Bot-Api-Secret-Token": "s3gredo"}


def test_webhook_responde_pelo_sender(tg):
    c, enviadas = tg
    r = c.post("/telegram/webhook", json=update("/saldo"), headers=H)
    assert r.status_code == 200
    assert len(enviadas) == 1 and enviadas[0][0] == DONO and "Total" in enviadas[0][1]


def test_webhook_rejeita_segredo_errado_ou_ausente(tg):
    c, enviadas = tg
    assert c.post("/telegram/webhook", json=update("/saldo"), headers={"X-Telegram-Bot-Api-Secret-Token": "x"}).status_code == 403
    assert c.post("/telegram/webhook", json=update("/saldo")).status_code == 403
    assert enviadas == []


def test_webhook_nao_autorizado_da_200_e_fica_mudo(tg):
    c, enviadas = tg
    assert c.post("/telegram/webhook", json=update("/saldo", chat=999), headers=H).status_code == 200
    assert enviadas == []


def test_webhook_fluxo_completo_com_reenvio(tg):
    c, enviadas = tg
    c.post("/telegram/webhook", json=update("/lancar 45,90 5.02.01 1.01.01 Mercado", uid=10), headers=H)
    c.post("/telegram/webhook", json=update("/ok", uid=11), headers=H)
    c.post("/telegram/webhook", json=update("/ok", uid=11), headers=H)          # Telegram reenviou
    assert len(enviadas) == 2
    saldo = c.get("/accounts/5.02.01/statement").json()
    assert saldo[-1]["running_cents"] == 4590 and len(saldo) == 1


def test_sem_configuracao_o_webhook_nega_tudo():
    factory = new_factory()
    with TestClient(create_app(factory, telegram_sender=lambda *a: None, telegram_allowed_ids=set())) as c:
        assert c.post("/telegram/webhook", json=update("/saldo")).status_code == 200
    factory.kw["bind"].dispose()


def test_falha_no_envio_nao_vira_erro_500():
    def quebrado(chat, texto):
        raise OSError("sem rede")
    factory = new_factory()
    app = create_app(factory, telegram_sender=quebrado, telegram_allowed_ids={DONO})
    with TestClient(app) as c:
        assert c.post("/telegram/webhook", json=update("/saldo")).status_code == 200   # senão o Telegram reenvia em loop
    factory.kw["bind"].dispose()
