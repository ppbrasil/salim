from datetime import date

import pytest

from salim.chart import seed_chart
from salim.ledger import Entry, balance, post_transaction
from salim.nlentry import parse_entry_text, suggest_account
from salim.telegram import Bot

HOJE = date(2026, 8, 12)


@pytest.fixture(autouse=True)
def _chart(session):
    seed_chart(session)


def _p(session, texto, **kw):
    return parse_entry_text(session, texto, HOJE, **kw)


def _par(p):
    return [(e["account_code"], e["amount_cents"]) for e in p["entries"]]


# ---- 7.1 texto livre -> proposta
def test_gasto_simples_com_palavra_chave(session):
    p = _p(session, "gastei 45,90 no mercado")
    assert p["ok"] and _par(p) == [("5.02.01", 4590), ("1.01.01", -4590)]
    assert p["description"] == "Mercado" and p["event_date"] == "2026-08-12"


def test_valor_inteiro_e_ontem(session):
    p = _p(session, "paguei 120 de luz ontem")
    assert _par(p)[0] == ("5.01.03", 12000) and p["event_date"] == "2026-08-11"


def test_valor_com_milhar_e_receita(session):
    p = _p(session, "recebi salário 5.000,00")
    assert _par(p) == [("1.01.01", 500000), ("4.01", -500000)]


def test_data_dia_mes(session):
    p = _p(session, "20/07 gasolina 150,00")
    assert _par(p)[0] == ("5.03.01", 15000) and p["event_date"] == "2026-07-20"


def test_valor_com_ponto_decimal(session):
    assert _par(_p(session, "mercado 45.90"))[0] == ("5.02.01", 4590)


def test_sem_valor_nao_e_lancamento(session):
    assert _p(session, "bom dia, tudo bem?") is None


def test_valor_sem_categoria_pede_ajuda(session):
    p = _p(session, "uber 23,40")
    assert p["ok"] is False and "categoria" in p["errors"][0]


# ---- 7.2 sugestão pelo histórico
def test_historico_sugere_a_conta_mais_usada(session):
    for _ in range(2):
        post_transaction(session, event_date=date(2026, 8, 1), description="Padaria do Zé",
                         entries=[Entry("5.02.02", 1000), Entry("1.01.01", -1000)])
    post_transaction(session, event_date=date(2026, 8, 2), description="Padaria do Zé",
                     entries=[Entry("5.02.01", 1000), Entry("1.01.01", -1000)])
    assert suggest_account(session, "padaria 18,00") == "5.02.02"
    assert _par(_p(session, "padaria 18,00"))[0] == ("5.02.02", 1800)


def test_sem_historico_nao_sugere(session):
    assert suggest_account(session, "uber") is None


# ---- ponto de extensão para LLM
def test_fallback_so_e_chamado_quando_as_regras_falham(session):
    chamadas = []

    def llm(texto, today, sess):
        chamadas.append(texto)
        return {"amount_cents": 2340, "debit_account": "5.03.01", "credit_account": "1.01.01", "description": "Uber"}

    assert _p(session, "gastei 45,90 no mercado", fallback=llm)["entries"][0]["account_code"] == "5.02.01"
    assert chamadas == []
    p = _p(session, "uber 23,40", fallback=llm)
    assert chamadas == ["uber 23,40"] and p["ok"] and _par(p)[0] == ("5.03.01", 2340)


# ---- integração com o Telegram
def test_telegram_texto_livre_vira_proposta_e_ok_registra(session, ctx_factory):
    bot = Bot(ctx_factory, allowed_ids={1}, clock=lambda: HOJE)
    resp = bot.handle({"update_id": 1, "message": {"chat": {"id": 1}, "from": {"id": 1}, "text": "gastei 45,90 no mercado"}})
    assert "R$ 45,90" in resp[0].text and "Supermercado" in resp[0].text and "/ok" in resp[0].text
    assert balance(session, "5.02.01") == 0
    bot.handle({"update_id": 2, "message": {"chat": {"id": 1}, "from": {"id": 1}, "text": "/ok"}})
    assert balance(session, "5.02.01") == 4590


def test_telegram_texto_sem_valor_mostra_ajuda(session, ctx_factory):
    bot = Bot(ctx_factory, allowed_ids={1}, clock=lambda: HOJE)
    resp = bot.handle({"update_id": 1, "message": {"chat": {"id": 1}, "from": {"id": 1}, "text": "oi"}})
    assert "/saldo" in resp[0].text


def test_telegram_valor_sem_categoria_explica(session, ctx_factory):
    bot = Bot(ctx_factory, allowed_ids={1}, clock=lambda: HOJE)
    resp = bot.handle({"update_id": 1, "message": {"chat": {"id": 1}, "from": {"id": 1}, "text": "uber 23,40"}})
    assert "categoria" in resp[0].text.lower() and "/lancar" in resp[0].text
