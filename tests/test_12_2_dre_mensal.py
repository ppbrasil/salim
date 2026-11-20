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


def test_tela_dre_mensal_tem_colunas_grupos_graficos_e_resultado(client):
    _dados(client)
    html = client.get("/ui/reports/dre", params={"start": "2026-08", "end": "2026-10"}).text
    assert all(m in html for m in ("ago/26", "set/26", "out/26"))              # uma coluna por mês
    assert 'data-code="5.02"' in html and 'data-code="5.02.01"' in html         # grupo e conta
    assert "<svg" in html and "<title>set/26 · Alimentação" in html
    assert "Resultado" in html and "4.250,00" in html                        # resultado de setembro


def test_tela_dre_sem_periodo_vai_do_primeiro_movimento_ate_o_mes_corrente(client):
    _dados(client)
    html = client.get("/ui/reports/dre", params={"today": "2026-10-20"}).text
    assert "ago/26" in html and "set/26" in html and "jul/26" not in html
    # mês corrente ainda sem movimento não vira coluna vazia
    assert "nov/26" not in client.get("/ui/reports/dre", params={"today": "2026-11-20"}).text


def test_tela_dre_vazia_nao_quebra(client):
    assert client.get("/ui/reports/dre").status_code == 200


def test_tela_dre_separa_receita_e_despesa_em_dois_graficos_cada(client):
    """Receita: total por mês + barra 100% por origem. Despesa: total por mês + barra 100% por grupo."""
    _dados(client)
    html = client.get("/ui/reports/dre", params={"start": "2026-08", "end": "2026-10"}).text
    for titulo in ("Receita por mês", "Receita por origem", "Despesa por mês", "Despesa por grupo"):
        assert titulo in html
    assert "Receitas × despesas" not in html                       # nada de receita e despesa no mesmo gráfico
    assert "<title>set/26 · Alimentação: R$ 550,00 (73%)</title>" in html     # fatia de 100% com valor e %
    assert "<title>set/26 · Salário: R$ 5.000,00 (100%)</title>" in html
    assert "<title>set/26 · despesa: R$ 750,00</title>" in html                # total do mês


def test_share_chart_soma_100_por_cento_e_pula_mes_vazio():
    from salim import viz
    svg = str(viz.share_chart(["2026-08", "2026-09"], [("A", 1, [300, 0]), ("B", 2, [100, 0])], label="x"))
    assert "(75%)" in svg and "(25%)" in svg and "100%" in svg      # eixo vai até 100%
    assert svg.count("<rect") == 2                                  # mês sem valor não desenha nada
