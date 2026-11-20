"""12.2 DRE mês a mês: uma coluna por mês, grupos somam os filhos, só linhas com movimento."""
from datetime import date

from salim import reports
from salim.chart import seed_chart
from salim.ledger import Entry, post_transaction


def _lanca(client, dia, conta, cents, contra="1.01.01", competence=None):
    e = {"account_code": conta, "amount_cents": cents}
    if competence:
        e["competence"] = competence
    client.post("/transactions", json={"event_date": dia, "description": f"{conta} {dia}", "entries": [
        e, {"account_code": contra, "amount_cents": -cents}]})


def _dados(client):
    _lanca(client, "2026-08-05", "5.02.01", 60000)      # mercado em agosto
    _lanca(client, "2026-09-05", "5.02.01", 40000)      # mercado em setembro
    _lanca(client, "2026-09-09", "5.02.02", 15000)      # restaurante em setembro
    _lanca(client, "2026-09-10", "5.03.01", 20000)      # combustível em setembro
    client.post("/transactions", json={"event_date": "2026-09-01", "description": "Salário", "entries": [
        {"account_code": "1.01.01", "amount_cents": 500000}, {"account_code": "4.01", "amount_cents": -500000}]})


def _dados_s(session):
    seed_chart(session)
    for dia, conta, cents in [(date(2026, 8, 5), "5.02.01", 60000), (date(2026, 9, 5), "5.02.01", 40000),
                              (date(2026, 9, 9), "5.02.02", 15000), (date(2026, 9, 10), "5.03.01", 20000)]:
        post_transaction(session, event_date=dia, description=conta, entries=[Entry(conta, cents), Entry("1.01.01", -cents)])
    post_transaction(session, event_date=date(2026, 9, 1), description="Salário",
                     entries=[Entry("1.01.01", 500000), Entry("4.01", -500000)])


def test_dre_mensal_colunas_e_grupos(session):
    _dados_s(session)
    m = reports.dre_monthly(session, date(2026, 8, 1), date(2026, 10, 31))
    assert m.months == ["2026-08", "2026-09", "2026-10"]
    linhas = {r.code: r for r in m.rows}
    assert linhas["5.02.01"].cents == [60000, 40000, 0]
    assert linhas["5.02"].cents == [60000, 55000, 0] and linhas["5.02"].is_group     # grupo soma os filhos
    assert linhas["5"].cents == [60000, 75000, 0]                                    # total de despesas
    assert linhas["4.01"].total_cents == 500000
    assert (m.income, m.expense, m.result) == ([0, 500000, 0], [60000, 75000, 0], [-60000, 425000, 0])


def test_dre_mensal_omite_contas_sem_movimento_e_ordena_por_codigo(session):
    _dados_s(session)
    m = reports.dre_monthly(session, date(2026, 8, 1), date(2026, 9, 30))
    codigos = [r.code for r in m.rows]
    assert "5.01.03" not in codigos and "5.01" not in codigos          # nada em Moradia
    assert codigos == sorted(codigos, key=lambda c: [int(x) for x in c.split(".")])
    assert next(r for r in m.rows if r.code == "5.02.01").depth == 2


def test_dre_mensal_respeita_competencia_nao_data_do_pagamento(session):
    seed_chart(session)
    post_transaction(session, event_date=date(2026, 9, 2), description="x", entries=[
        Entry("5.02.01", 30000, competence=date(2026, 8, 15)), Entry("1.01.01", -30000)])
    m = reports.dre_monthly(session, date(2026, 8, 1), date(2026, 9, 30))
    assert next(r for r in m.rows if r.code == "5.02.01").cents == [30000, 0]


def test_api_dre_mensal(client):
    _dados(client)
    r = client.get("/reports/dre-monthly", params={"start": "2026-08-01", "end": "2026-09-30"}).json()
    assert r["months"] == ["2026-08", "2026-09"] and r["result"] == [-60000, 425000]
    assert {x["code"]: x["cents"] for x in r["rows"]}["5.02"] == [60000, 55000]
