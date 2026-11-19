CSV = "Data;Descrição;Valor\n05/08/2026;MERCADO XYZ;-45,90\n06/08/2026;SALARIO ACME;5.000,00\n"


def test_fluxo_completo_pela_api(client):
    r = client.post("/imports/csv", json={"account_code": "1.01.01", "csv_text": CSV})
    assert r.status_code == 201 and r.json() == {"created": 2, "skipped": 0, "errors": []}
    assert client.post("/imports/csv", json={"account_code": "1.01.01", "csv_text": CSV}).json()["skipped"] == 2
    itens = client.get("/imports", params={"status": "pending"}).json()
    assert [(i["description"], i["amount_cents"]) for i in itens] == [("MERCADO XYZ", -4590), ("SALARIO ACME", 500000)]
    r = client.post(f"/imports/{itens[0]['id']}/book", json={"counter_account": "5.02.01"})
    assert r.status_code == 201 and r.json()["transaction_id"]
    assert client.post(f"/imports/{itens[1]['id']}/ignore").status_code == 200
    assert client.get("/imports", params={"status": "pending"}).json() == []
    assert client.get("/accounts/5.02.01/statement").json()[-1]["running_cents"] == 4590


def test_match_pela_api(client):
    client.post("/transactions", json={"event_date": "2026-08-05", "description": "Mercado", "entries": [
        {"account_code": "5.02.01", "amount_cents": 4590}, {"account_code": "1.01.01", "amount_cents": -4590}]})
    client.post("/imports/csv", json={"account_code": "1.01.01", "csv_text": CSV})
    assert client.post("/imports/match").json() == {"matched": 1}
    assert [i["status"] for i in client.get("/imports").json()] == ["matched", "pending"]


def test_erros_viram_422(client):
    assert client.post("/imports/csv", json={"account_code": "5.02.01", "csv_text": CSV}).status_code == 422
    assert client.post("/imports/csv", json={"account_code": "1.01.01", "csv_text": "x;y\n1;2"}).status_code == 422
    assert client.post("/imports/999/book", json={"counter_account": "5.02.01"}).status_code == 422
    assert client.post("/imports/999/ignore").status_code == 422
