def _cartao(client, code="2.01.01"):
    r = client.post("/accounts", json={"code": code, "name": "Nubank", "type": "liability", "parent_code": "2.01",
                                       "tracks_obligations": True, "closing_day": 25, "due_day": 5})
    assert r.status_code == 201, r.text


def test_criar_conta_e_conflito(client):
    r = client.post("/accounts", json={"code": "1.01.09", "name": "Poupança", "type": "asset", "parent_code": "1.01",
                                       "is_cash": True})
    assert r.status_code == 201
    assert client.post("/accounts", json={"code": "1.01.09", "name": "x", "type": "asset"}).status_code == 409
    assert client.post("/accounts", json={"code": "9", "name": "x", "type": "asset", "is_group": True,
                                          "is_cash": True}).status_code == 422
    assert client.post("/accounts", json={"code": "9.1", "name": "x", "type": "asset",
                                          "parent_code": "7.7"}).status_code == 422


def test_conta_a_pagar_lista_e_filtra_por_status(client):
    r = client.post("/obligations/bills", json={
        "event_date": "2026-08-10", "description": "Luz", "expense_account": "5.01.03", "amount_cents": 10000,
        "due_date": "2026-08-20", "counterparty": "Copel"})
    assert r.status_code == 201 and r.json()["status"] in ("a_vencer", "atrasada")
    lista = client.get("/obligations", params={"today": "2026-08-25", "status": "atrasada"}).json()
    assert len(lista) == 1 and lista[0]["days_late"] == 5 and lista[0]["counterparty"] == "Copel"
    assert client.get("/obligations", params={"today": "2026-08-15", "status": "atrasada"}).json() == []


def test_compra_no_cartao_parcelada_e_pagamento(client):
    _cartao(client)
    r = client.post("/card-purchases", json={"card_code": "2.01.01", "event_date": "2026-10-10", "description": "TV",
                                             "items": [{"account_code": "5.99", "amount_cents": 30000}], "installments": 3})
    assert r.status_code == 201
    faturas = r.json()
    assert [f["reference"] for f in faturas] == ["2026-10", "2026-11", "2026-12"]
    r = client.post("/obligations/settle", json={
        "event_date": "2026-11-05", "cash_account_code": "1.01.01",
        "items": [{"obligation_id": faturas[0]["id"], "amount_cents": None}]})
    assert r.status_code == 201
    lista = client.get("/obligations", params={"today": "2026-11-06"}).json()
    assert [o["reference"] for o in lista] == ["2026-11", "2026-12"]


def test_parcelar_e_renegociar_pela_api(client):
    _cartao(client)
    f = client.post("/card-purchases", json={"card_code": "2.01.01", "event_date": "2026-06-28", "description": "Mercado",
                                             "items": [{"account_code": "5.02.01", "amount_cents": 110000}]}).json()[0]
    r = client.post(f"/obligations/{f['id']}/installments", json={
        "event_date": "2026-08-04", "installments": 5, "first_due_date": "2026-09-05", "interest_cents": 10000})
    assert r.status_code == 201 and [p["balance_cents"] for p in r.json()] == [24000] * 5
    ids = [p["id"] for p in r.json()[1:3]]
    r = client.post("/obligations/consolidate", json={"obligation_ids": ids, "event_date": "2026-11-19",
                                                      "due_date": "2026-11-30", "fine_cents": 3000})
    assert r.status_code == 201 and r.json()["balance_cents"] == 51000
    r = client.post(f"/obligations/{r.json()['id']}/reschedule", json={"planned_date": "2026-12-02"})
    assert r.status_code == 200 and r.json()["planned_date"] == "2026-12-02"


def test_reembolso_pela_api(client):
    r = client.post("/reimbursable-expenses", json={
        "event_date": "2026-07-22", "description": "Táxi", "expense_account": "5.03.01", "my_share_cents": 3000,
        "other_share_cents": 3000, "counterparty": "Ana", "due_date": "2026-08-01", "payer_account_code": "1.01.01"})
    assert r.status_code == 201 and r.json()["direction"] == "receber" and r.json()["balance_cents"] == 3000


def test_erros_de_negocio_viram_422(client):
    r = client.post("/obligations/settle", json={"event_date": "2026-11-05", "cash_account_code": "1.01.01",
                                                 "items": [{"obligation_id": 999, "amount_cents": 10}]})
    assert r.status_code == 422 and "999" in r.json()["detail"]
    r = client.post("/card-purchases", json={"card_code": "1.01.01", "event_date": "2026-10-10", "description": "x",
                                             "items": [{"account_code": "5.99", "amount_cents": 1}]})
    assert r.status_code == 422
