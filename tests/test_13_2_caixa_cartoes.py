"""13.4 Caixa projetado enxerga as faturas futuras do cartão (parcelas já alocadas, vencimento do cartão)."""
from datetime import date

from salim import cards, reports
from salim.chart import seed_chart
from salim.obligations import register_card_purchase

HOJE = date(2026, 11, 20)


def _cartao_com_parcelas(session, parcelas=8):
    seed_chart(session)
    cards.create_card(session, name="Santander Unique", brand="Visa", last4="0103", closing_day=12, due_day=19)
    register_card_purchase(session, card_code="2.01.01", event_date=date(2026, 11, 20), description="Notebook",
                           items=[("5.02.01", 80000)], installments=parcelas)


def test_parcelas_viram_faturas_futuras_com_o_vencimento_do_cartao(session):
    _cartao_com_parcelas(session, 3)
    s = cards.card_summary(session, "2.01.01", HOJE)
    assert [(i.reference, i.due_date, i.balance_cents) for i in s.invoices] == [
        ("2026-12", date(2026, 12, 19), 26668), ("2027-01", date(2027, 1, 19), 26666), ("2027-02", date(2027, 2, 19), 26666)]


def test_horizonte_vai_ate_a_ultima_fatura_em_aberto(session):
    _cartao_com_parcelas(session, 8)
    assert reports.cash_horizon(session, HOJE) == 8                 # dez/26 … jul/27
    assert reports.cash_horizon(session, HOJE, minimo=3) >= 3


def test_horizonte_sem_titulos_usa_o_minimo(session):
    seed_chart(session)
    assert reports.cash_horizon(session, HOJE, minimo=3) == 3


def test_caixa_mensal_separa_o_que_e_fatura_de_cartao(session):
    _cartao_com_parcelas(session, 3)
    c = reports.cash_monthly(session, date(2026, 11, 1), date(2026, 11, 30), HOJE, future_months=3)
    por_mes = {r.month: r for r in c.months}
    assert por_mes["2026-12"].expected_out_cents == 26668 == por_mes["2026-12"].expected_cards_cents
    assert por_mes["2027-02"].expected_cards_cents == 26666
    assert por_mes["2026-11"].expected_cards_cents == 0


def test_tela_do_caixa_mostra_todos_os_meses_com_fatura_e_a_linha_de_cartoes(client):
    client.post("/cards", json={"name": "Santander Unique", "brand": "Visa", "last4": "0103", "closing_day": 12, "due_day": 19})
    client.post("/card-purchases", json={"card_code": "2.01.01", "event_date": "2026-11-20", "description": "Notebook",
                                         "items": [{"account_code": "5.02.01", "amount_cents": 80000}], "installments": 8})
    html = client.get("/ui/reports/cash", params={"today": "2026-11-20"}).text
    assert "jul/27" in html and "faturas de cartão" in html.lower()
