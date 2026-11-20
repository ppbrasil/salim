"""13.1–13.3 Módulo de cartões: cadastro, fatura aberta sempre, saldo devido (outstanding) por cartão."""
from datetime import date

import pytest

from salim import cards
from salim.chart import seed_chart
from salim.ledger import InvalidAccountError, balance
from salim.obligations import register_card_purchase

HOJE = date(2026, 11, 20)


def _cartao(session, **kw):
    seed_chart(session)
    dados = dict(name="Santander Unique", brand="visa", last4="0103", closing_day=25, due_day=5)
    dados.update(kw)
    return cards.create_card(session, **dados)


def test_cadastro_cria_conta_de_passivo_com_codigo_proprio_e_dados_do_cartao(session):
    c = _cartao(session)
    assert (c.code, c.card_brand, c.card_last4, c.closing_day, c.due_day) == ("2.01.01", "Visa", "0103", 25, 5)
    assert c.tracks_obligations and c.type.value == "liability"
    outro = cards.create_card(session, name="BTG Black", brand="Mastercard", last4="7370", closing_day=3, due_day=10)
    assert outro.code == "2.01.02"


@pytest.mark.parametrize("campo,valor", [("last4", "12a4"), ("last4", "123"), ("brand", "Diners Fake"),
                                         ("closing_day", 0), ("due_day", 32), ("name", "  ")])
def test_cadastro_rejeita_dados_invalidos(session, campo, valor):
    with pytest.raises(InvalidAccountError):
        _cartao(session, **{campo: valor})


def test_melhor_dia_de_compra_e_o_dia_seguinte_ao_fechamento(session):
    _cartao(session)
    assert cards.card_summary(session, "2.01.01", HOJE).best_purchase_day == 26
    c = cards.create_card(session, name="Fecha dia 31", last4="1111", closing_day=31, due_day=10)
    assert cards.card_summary(session, c.code, HOJE).best_purchase_day == 1


def test_cartao_novo_ja_tem_fatura_aberta_do_ciclo_mesmo_sem_compras(session):
    _cartao(session)
    s = cards.card_summary(session, "2.01.01", HOJE)
    assert s.outstanding_cents == 0
    assert (s.open_closing, s.open_due, s.open_cents) == (date(2026, 11, 25), date(2026, 12, 5), 0)
    assert [(i.status, i.virtual) for i in s.invoices] == [("aberta", True)]


def test_depois_do_fechamento_a_fatura_aberta_passa_para_o_proximo_ciclo(session):
    _cartao(session)
    s = cards.card_summary(session, "2.01.01", date(2026, 11, 26))
    assert (s.open_closing, s.open_due) == (date(2026, 12, 25), date(2027, 1, 5))


def test_outstanding_soma_fechadas_aberta_e_futuras_e_bate_com_o_saldo_da_conta(session):
    _cartao(session)
    register_card_purchase(session, card_code="2.01.01", event_date=date(2026, 10, 10), description="Mercado",
                           items=[("5.02.01", 10000)])                       # fatura de 25/10: fechada
    register_card_purchase(session, card_code="2.01.01", event_date=date(2026, 11, 10), description="Farmácia",
                           items=[("5.02.01", 5000)])                        # fatura de 25/11: aberta
    register_card_purchase(session, card_code="2.01.01", event_date=date(2026, 11, 12), description="TV 3x",
                           items=[("5.02.01", 30000)], installments=3)       # 25/11, 25/12, 25/01
    s = cards.card_summary(session, "2.01.01", HOJE)
    assert (s.closed_cents, s.open_cents, s.future_cents) == (10000, 15000, 20000)
    assert s.outstanding_cents == 45000 == balance(session, "2.01.01")
    assert [i.status for i in s.invoices] == ["fechada", "aberta", "futura", "futura"]
    assert s.invoices[0].due_date == date(2026, 11, 5) and s.invoices[0].days_late == 15


def test_fatura_fechada_quitada_some_da_lista(session):
    from salim.obligations import settle_obligations
    _cartao(session)
    f = register_card_purchase(session, card_code="2.01.01", event_date=date(2026, 10, 10), description="Mercado",
                               items=[("5.02.01", 10000)])[0]
    settle_obligations(session, event_date=date(2026, 11, 5), items=[(f.id, None)], cash_account_code="1.01.01",
                       description="Pagamento fatura")
    s = cards.card_summary(session, "2.01.01", HOJE)
    assert s.closed_cents == 0 and [i.status for i in s.invoices] == ["aberta"]


def test_listar_cartoes_so_traz_cartoes_ativos(session):
    _cartao(session)
    assert [c.code for c in cards.list_cards(session, HOJE)] == ["2.01.01"]


def test_editar_cartao_muda_dados_e_fechamento_vale_so_para_o_futuro(session):
    _cartao(session)
    register_card_purchase(session, card_code="2.01.01", event_date=date(2026, 11, 10), description="Farmácia",
                           items=[("5.02.01", 5000)])
    cards.update_card(session, "2.01.01", closing_day=28, due_day=8, last4="9999", brand="Elo", name="Unique")
    s = cards.card_summary(session, "2.01.01", HOJE)
    assert (s.name, s.brand, s.last4, s.closing_day, s.due_day) == ("Unique", "Elo", "9999", 28, 8)
    assert s.open_cents == 5000                      # a fatura já aberta continua com o que tinha


# ---- API e telas
def test_api_cadastra_lista_e_edita_cartao(client):
    r = client.post("/cards", json={"name": "Santander Unique", "brand": "Visa", "last4": "0103",
                                    "closing_day": 25, "due_day": 5})
    assert r.status_code == 201 and r.json()["code"] == "2.01.01" and r.json()["best_purchase_day"] == 26
    lista = client.get("/cards", params={"today": "2026-11-20"}).json()
    assert [(c["name"], c["outstanding_cents"], c["open_closing"]) for c in lista] == [("Santander Unique", 0, "2026-11-25")]
    assert client.patch("/cards/2.01.01", json={"last4": "4444"}).json()["last4"] == "4444"
    assert client.post("/cards", json={"name": "x", "last4": "abc", "closing_day": 1, "due_day": 2}).status_code == 422
    assert client.get("/cards/9.99").status_code == 404


def test_tela_de_cartoes_mostra_saldo_fatura_aberta_e_cadastro(client):
    client.post("/cards", json={"name": "Santander Unique", "brand": "Visa", "last4": "0103", "closing_day": 25, "due_day": 5})
    client.post("/card-purchases", json={"card_code": "2.01.01", "event_date": "2026-11-10", "description": "Farmácia",
                                         "items": [{"account_code": "5.02.01", "amount_cents": 12345}]})
    html = client.get("/ui/cards", params={"today": "2026-11-20"}).text
    assert "Santander Unique" in html and "0103" in html and "Visa" in html
    assert "123,45" in html and "25/11" in html and "05/12" in html and "melhor dia" in html.lower()
    detalhe = client.get("/ui/cards/2.01.01", params={"today": "2026-11-20"})
    assert detalhe.status_code == 200 and "Farmácia" in detalhe.text
    r = client.post("/ui/cards", data={"name": "BTG", "brand": "Mastercard", "last4": "7370", "closing_day": "3",
                                        "due_day": "10"}, follow_redirects=False)
    assert r.status_code == 303 and "BTG" in client.get("/ui/cards").text


def test_tela_de_cartoes_erro_de_cadastro_aparece_na_tela(client):
    r = client.post("/ui/cards", data={"name": "BTG", "brand": "Mastercard", "last4": "73", "closing_day": "3",
                                        "due_day": "10"})
    assert r.status_code == 422 and "4 dígitos" in r.text
