"""Contrato comum: o mesmo comportamento vale para Telegram e WhatsApp."""
import hashlib
import hmac
import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

from salim.app import create_app
from salim.chart import seed_chart
from salim.channels import TelegramChannel, WhatsAppChannel
from salim.db import make_session_factory
from salim.ledger import Entry, balance, post_transaction
from salim.telegram import Bot

HOJE = date(2026, 8, 12)


def tg_native(text, uid, user):
    return {"update_id": uid, "message": {"chat": {"id": user}, "from": {"id": user}, "text": text}}


def wa_native(text, uid, user):
    return {"object": "whatsapp_business_account", "entry": [{"changes": [{"value": {"messages": [
        {"id": f"wamid.{uid}", "from": user, "type": "text", "text": {"body": text}}]}}]}]}


CANAIS = {"telegram": (TelegramChannel, 111, tg_native), "whatsapp": (WhatsAppChannel, "5541999990000", wa_native)}


@pytest.fixture(params=sorted(CANAIS))
def canal(request, session, ctx_factory):
    seed_chart(session)
    cls, dono, native = CANAIS[request.param]
    bot = Bot(ctx_factory, allowed_ids={dono}, clock=lambda: HOJE, channel=cls())

    def falar(texto, uid, user=dono):
        return [r for r in bot.handle(native(texto, uid, user))]
    return falar, dono, request.param


def test_saldo_e_resposta_vai_para_quem_perguntou(canal, session):
    falar, dono, _ = canal
    post_transaction(session, event_date=date(2026, 8, 1), description="Salário",
                     entries=[Entry("1.01.01", 500000), Entry("4.01", -500000)])
    [r] = falar("/saldo", 1)
    assert r.chat_id == dono and "R$ 5.000,00" in r.text


def test_nao_autorizado_fica_mudo(canal):
    falar, _, nome = canal
    intruso = 999 if nome == "telegram" else "5500000000000"
    assert falar("/saldo", 1, user=intruso) == []


def test_lancar_confirmar_e_reenvio_nao_duplica(canal, session):
    falar, _, _ = canal
    assert "/ok" in falar("/lancar 45,90 5.02.01 1.01.01 Mercado", 10)[0].text
    assert falar("/ok", 11)[0].text.startswith("Registrado")
    assert falar("/ok", 11) == []                                   # entrega repetida do mesmo id
    assert balance(session, "5.02.01") == 4590


def test_texto_livre_vira_proposta(canal):
    falar, _, _ = canal
    assert "Supermercado" in falar("gastei 45,90 no mercado", 1)[0].text


def test_entrada_sem_texto_e_ignorada(canal):
    falar, dono, nome = canal
    bot_native = CANAIS[nome][2]
    vazio = bot_native("", 1, dono)
    assert falar("", 2) == []


def test_referencia_do_lancamento_identifica_o_canal(canal, session):
    falar, _, nome = canal
    falar("/lancar 10,00 5.02.01 1.01.01 x", 10)
    falar("/ok", 11)
    from salim.models import Transaction
    tx = session.query(Transaction).one()
    assert tx.source == nome and tx.external_ref.startswith("tg:" if nome == "telegram" else "wa:")


# ---- específicos do WhatsApp
def test_whatsapp_ignora_notificacao_de_status(session, ctx_factory):
    bot = Bot(ctx_factory, allowed_ids={"5541999990000"}, clock=lambda: HOJE, channel=WhatsAppChannel())
    payload = {"entry": [{"changes": [{"value": {"statuses": [{"id": "wamid.1", "status": "delivered"}]}}]}]}
    assert bot.handle(payload) == []


def test_whatsapp_varias_mensagens_no_mesmo_envio(session, ctx_factory):
    seed_chart(session)
    bot = Bot(ctx_factory, allowed_ids={"55"}, clock=lambda: HOJE, channel=WhatsAppChannel())
    payload = {"entry": [{"changes": [{"value": {"messages": [
        {"id": "a", "from": "55", "type": "text", "text": {"body": "/saldo"}},
        {"id": "b", "from": "55", "type": "image"},
        {"id": "c", "from": "55", "type": "text", "text": {"body": "/faturas"}}]}}]}]}
    assert len(bot.handle(payload)) == 2


@pytest.fixture
def wa_http():
    factory = make_session_factory("sqlite://")
    enviadas = []
    app = create_app(factory, whatsapp_sender=lambda to, texto: enviadas.append((to, texto)),
                     whatsapp_allowed={"5541999990000"}, whatsapp_verify_token="verifica", whatsapp_app_secret="segredo")
    with TestClient(app) as c:
        yield c, enviadas
    factory.kw["bind"].dispose()


def _assinar(corpo: bytes, segredo="segredo") -> dict:
    return {"X-Hub-Signature-256": "sha256=" + hmac.new(segredo.encode(), corpo, hashlib.sha256).hexdigest(),
            "Content-Type": "application/json"}


def test_whatsapp_verificacao_do_webhook(wa_http):
    c, _ = wa_http
    ok = c.get("/whatsapp/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "verifica", "hub.challenge": "1234"})
    assert ok.status_code == 200 and ok.text == "1234"
    assert c.get("/whatsapp/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "errado", "hub.challenge": "1"}).status_code == 403


def test_whatsapp_post_assinado_responde_e_sem_assinatura_e_recusado(wa_http):
    c, enviadas = wa_http
    corpo = json.dumps(wa_native("/saldo", 1, "5541999990000")).encode()
    assert c.post("/whatsapp/webhook", content=corpo, headers=_assinar(corpo)).status_code == 200
    assert enviadas and enviadas[0][0] == "5541999990000" and "Total" in enviadas[0][1]
    assert c.post("/whatsapp/webhook", content=corpo, headers={"Content-Type": "application/json"}).status_code == 403
    assert c.post("/whatsapp/webhook", content=corpo, headers=_assinar(corpo, "outro")).status_code == 403
    assert len(enviadas) == 1
