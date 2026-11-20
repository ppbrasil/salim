"""12.4 Contas a pagar e a receber em telas separadas; reembolso por pedido (evento) com itens."""
from datetime import date

from salim import obligations as obl
from salim.chart import seed_chart
from salim.ledger import Entry, post_transaction


def _conta_luz(client):
    client.post("/obligations/bills", json={"event_date": "2026-08-10", "description": "Luz", "expense_account": "5.01.03",
                                            "amount_cents": 10000, "due_date": "2026-08-20", "counterparty": "Copel"})


def _pedido(client, **kw):
    corpo = {"event_date": "2026-08-17", "description": "Hotel", "amount_cents": 50000, "expense_account": "5.05.01",
             "reference": "Viagem SP ago/26", "counterparty": "Tupi", "due_date": "2026-09-30"}
    corpo.update(kw)
    return client.post("/reimbursements", json=corpo)


# ---- itens de um título
def test_itens_do_titulo_lista_o_que_compoe_o_saldo(session):
    seed_chart(session)
    o = obl.register_bill(session, event_date=date(2026, 8, 10), description="Luz", expense_account="5.01.03",
                          amount_cents=10000, due_date=date(2026, 8, 20), counterparty="Copel")
    obl.settle_obligations(session, event_date=date(2026, 8, 20), items=[(o.id, 4000)], cash_account_code="1.01.01",
                           description="Pagamento parcial luz")
    itens = obl.obligation_items(session, [o.id])[o.id]
    assert [(i.date, i.description, i.cents) for i in itens] == [
        (date(2026, 8, 10), "Luz", 10000), (date(2026, 8, 20), "Pagamento parcial luz", -4000)]


# ---- pedido de reembolso
def test_novo_pedido_com_item_e_segundo_item_no_mesmo_pedido(client):
    r = _pedido(client)
    assert r.status_code == 201
    oid = r.json()["id"]
    r2 = client.post(f"/reimbursements/{oid}/items", json={"event_date": "2026-08-18", "description": "Jantar",
                                                           "amount_cents": 20000, "expense_account": "5.02.02"})
    assert r2.status_code == 201
    t = next(o for o in client.get("/obligations", params={"today": "2026-08-25"}).json() if o["id"] == oid)
    assert (t["balance_cents"], t["direction"], t["reference"], t["counterparty"]) == (70000, "receber", "Viagem SP ago/26", "Tupi")


def test_item_do_pedido_neutraliza_a_despesa_na_propria_categoria(client):
    # a despesa foi paga com meu dinheiro (entra no DRE) e o pedido a devolve
    client.post("/transactions", json={"event_date": "2026-08-17", "description": "Hotel", "entries": [
        {"account_code": "5.05.01", "amount_cents": 50000}, {"account_code": "1.01.01", "amount_cents": -50000}]})
    _pedido(client)
    dre = client.get("/reports/dre", params={"start": "2026-08-01", "end": "2026-08-31"}).json()
    assert dre["expense_cents"] == 0                       # o custo do evento não é meu: a Tupi devolve


def test_item_em_pedido_inexistente_ou_quitado_da_422(client):
    corpo = {"event_date": "2026-08-18", "description": "x", "amount_cents": 100, "expense_account": "5.99"}
    assert client.post("/reimbursements/999/items", json=corpo).status_code == 422
    oid = _pedido(client).json()["id"]
    client.post("/obligations/settle", json={"event_date": "2026-09-01", "cash_account_code": "1.01.01",
                                            "items": [{"obligation_id": oid}]})
    assert client.post(f"/reimbursements/{oid}/items", json=corpo).status_code == 422


# ---- telas
def test_tela_a_pagar_so_tem_o_que_pagar_com_acao_de_pagar(client):
    _conta_luz(client)
    _pedido(client)
    html = client.get("/ui/payables", params={"today": "2026-08-25"}).text
    assert "Copel" in html and "atrasada" in html and "5 dias" in html and "R$ 100,00" in html
    assert "Viagem SP" not in html                                            # a receber fica na outra tela
    assert 'action="/ui/obligations/' in html and "Pagar" in html and 'name="cash_account_code"' in html


def test_tela_a_receber_agrupa_por_pedido_e_mostra_os_itens(client):
    oid = _pedido(client).json()["id"]
    client.post(f"/reimbursements/{oid}/items", json={"event_date": "2026-08-18", "description": "Jantar cliente",
                                                      "amount_cents": 20000, "expense_account": "5.02.02"})
    html = client.get("/ui/receivables", params={"today": "2026-08-25"}).text
    assert "Viagem SP ago/26" in html and "Tupi" in html and "R$ 700,00" in html
    assert "Hotel" in html and "Jantar cliente" in html and "R$ 500,00" in html and "R$ 200,00" in html
    assert "Receber" in html and 'name="cash_account_code"' in html


def test_pagar_pela_tela_baixa_o_titulo_e_sai_do_caixa(client):
    _conta_luz(client)
    oid = client.get("/obligations", params={"today": "2026-08-25"}).json()[0]["id"]
    r = client.post(f"/ui/obligations/{oid}/settle", data={"event_date": "2026-08-25", "amount": "100,00",
                    "cash_account_code": "1.01.01", "back": "/ui/payables"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/ui/payables"
    assert client.get("/obligations", params={"today": "2026-08-25"}).json() == []
    assert client.get("/accounts/1.01.01/statement").json()[-1]["delta_cents"] == -10000


def test_receber_parcialmente_pela_tela(client):
    oid = _pedido(client).json()["id"]
    r = client.post(f"/ui/obligations/{oid}/settle", data={"event_date": "2026-09-05", "amount": "200,00",
                    "cash_account_code": "1.01.01", "back": "/ui/receivables"}, follow_redirects=False)
    assert r.status_code == 303
    t = client.get("/obligations", params={"today": "2026-09-06"}).json()[0]
    assert t["balance_cents"] == 30000
    assert client.get("/accounts/1.01.01/statement").json()[-1]["delta_cents"] == 20000      # entrou dinheiro


def test_erro_ao_pagar_pela_tela_mostra_mensagem_e_nao_baixa(client):
    _conta_luz(client)
    oid = client.get("/obligations", params={"today": "2026-08-25"}).json()[0]["id"]
    r = client.post(f"/ui/obligations/{oid}/settle", data={"event_date": "2026-08-25", "amount": "999,00",
                    "cash_account_code": "1.01.01", "back": "/ui/payables"})
    assert r.status_code == 422 and "maior que o saldo" in r.text
    assert client.get("/obligations", params={"today": "2026-08-25"}).json()[0]["balance_cents"] == 10000


def test_pedido_sem_referencia_mostra_a_descricao_do_primeiro_item(client):
    _pedido(client, reference=None)
    html = client.get("/ui/receivables", params={"today": "2026-08-25"}).text
    assert "Hotel" in html and "reimbursement" not in html
