"""12.3 Caixa mês a mês: entrou, saiu, líquido, saldo, previsto pelos títulos e desvio contra o orçado."""
from datetime import date

from salim import budget as bud, reports
from salim.chart import seed_chart
from salim.ledger import Entry, post_transaction
from salim.obligations import register_bill


def _dados(session):
    seed_chart(session)
    post_transaction(session, event_date=date(2026, 8, 5), description="Salário",
                     entries=[Entry("1.01.01", 500000), Entry("4.01", -500000)])
    post_transaction(session, event_date=date(2026, 8, 6), description="Mercado",
                     entries=[Entry("5.02.01", 60000), Entry("1.01.01", -60000)])
    register_bill(session, event_date=date(2026, 8, 10), description="Luz", expense_account="5.01.03",
                  amount_cents=10000, due_date=date(2026, 9, 20), counterparty="Copel")


def test_caixa_mensal_executado_saldo_e_previsto(session):
    _dados(session)
    c = reports.cash_monthly(session, date(2026, 8, 1), date(2026, 8, 1), today=date(2026, 8, 12), future_months=1)
    ago, setembro = c.months
    assert (ago.month, ago.inflow_cents, ago.outflow_cents, ago.net_cents, ago.closing_cents) == ("2026-08", 500000, 60000, 440000, 440000)
    assert not ago.is_future and setembro.is_future
    assert (setembro.inflow_cents, setembro.outflow_cents) == (0, 0)                 # nada executado ainda
    assert (setembro.expected_out_cents, setembro.closing_cents) == (10000, 430000)  # a conta de luz vence em setembro


def test_caixa_mensal_saldo_inicial_vem_do_que_veio_antes_da_janela(session):
    _dados(session)
    c = reports.cash_monthly(session, date(2026, 9, 1), date(2026, 9, 1), today=date(2026, 9, 12), future_months=0)
    assert c.months[0].closing_cents == 440000


def test_desvio_contra_orcamento(session):
    _dados(session)
    c = reports.cash_monthly(session, date(2026, 8, 1), date(2026, 8, 1), today=date(2026, 9, 12), future_months=0)
    assert c.months[0].budget_net_cents is None and c.months[0].deviation_cents is None   # sem orçamento, sem desvio
    bud.set_budget(session, "5.02.01", 90000)
    bud.set_budget(session, "4.01", 500000)
    c = reports.cash_monthly(session, date(2026, 8, 1), date(2026, 8, 1), today=date(2026, 9, 12), future_months=0)
    m = c.months[0]
    assert (m.budget_net_cents, m.deviation_cents) == (410000, 30000)


def test_orcamento_de_grupo_e_de_filho_nao_conta_duas_vezes(session):
    seed_chart(session)
    bud.set_budget(session, "5.02", 100000)
    bud.set_budget(session, "5.02.01", 60000)
    assert bud.budget_net_cents(session, date(2026, 8, 1)) == -100000       # vale o do grupo (mais alto)


def test_tela_caixa_mensal(client):
    client.post("/transactions", json={"event_date": "2026-08-05", "description": "Salário", "entries": [
        {"account_code": "1.01.01", "amount_cents": 500000}, {"account_code": "4.01", "amount_cents": -500000}]})
    client.post("/obligations/bills", json={"event_date": "2026-08-10", "description": "Luz", "expense_account": "5.01.03",
                                            "amount_cents": 10000, "due_date": "2026-09-20", "counterparty": "Copel"})
    html = client.get("/ui/reports/cash", params={"today": "2026-08-12"}).text
    assert "ago/26" in html and "set/26" in html and "Saldo ao fim do mês" in html and "Entradas" in html
    assert "5.000,00" in html and "<svg" in html
