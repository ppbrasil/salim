"""M6: "hoje" é o dia em São Paulo, não o dia UTC do servidor (a Vercel roda em UTC)."""
from datetime import date, datetime, timezone

import pytest

from salim import clock


def utc(y, mo, d, h, mi):
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc)


def test_as_23h30_em_sao_paulo_ainda_e_o_mesmo_dia(monkeypatch):
    monkeypatch.setattr(clock, "_utcnow", lambda: utc(2026, 8, 13, 2, 30))     # UTC já virou o dia
    assert clock.today() == date(2026, 8, 12)


def test_a_meia_noite_em_sao_paulo_vira_o_dia(monkeypatch):
    monkeypatch.setattr(clock, "_utcnow", lambda: utc(2026, 8, 13, 3, 0))
    assert clock.today() == date(2026, 8, 13)


def test_virada_de_mes_e_de_ano(monkeypatch):
    monkeypatch.setattr(clock, "_utcnow", lambda: utc(2027, 1, 1, 1, 0))       # 22h de 31/12 em SP
    assert clock.today() == date(2026, 12, 31)


def test_fuso_pode_ser_trocado_por_ambiente(monkeypatch):
    monkeypatch.setenv("SALIM_TZ", "Asia/Tokyo")
    monkeypatch.setattr(clock, "_utcnow", lambda: utc(2026, 8, 12, 20, 0))
    assert clock.today() == date(2026, 8, 13)


def test_api_usa_o_dia_de_sao_paulo_para_atraso(client, monkeypatch):
    client.post("/obligations/bills", json={
        "event_date": "2026-08-01", "description": "Luz", "expense_account": "5.01.03", "amount_cents": 10000,
        "due_date": "2026-08-12"})
    monkeypatch.setattr(clock, "_utcnow", lambda: utc(2026, 8, 13, 2, 30))     # UTC: dia 13; SP: dia 12 às 23h30
    (titulo,) = client.get("/obligations").json()
    assert titulo["status"] == "a_vencer"            # vence hoje em SP: ainda não está atrasada
    monkeypatch.setattr(clock, "_utcnow", lambda: utc(2026, 8, 13, 3, 30))
    (titulo,) = client.get("/obligations").json()
    assert titulo["status"] == "atrasada" and titulo["days_late"] == 1


def test_bot_e_mcp_usam_o_mesmo_relogio_por_padrao():
    import inspect
    from salim import mcp_server, telegram
    assert inspect.signature(telegram.Bot.__init__).parameters["clock"].default is clock.today
    assert inspect.signature(mcp_server.build_server).parameters["clock"].default is clock.today
