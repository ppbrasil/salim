def _tx(entries, **kw):
    return {"event_date": "2026-11-05", "description": "x", "entries": entries, **kw}


def test_cria_lancamento_201(client):
    r = client.post("/transactions", json=_tx([
        {"account_code": "5.99", "amount_cents": 1000}, {"account_code": "1.01.01", "amount_cents": -1000}]))
    assert r.status_code == 201
    assert r.json()["id"] >= 1


def test_soma_diferente_de_zero_422(client):
    r = client.post("/transactions", json=_tx([
        {"account_code": "5.99", "amount_cents": 1000}, {"account_code": "1.01.01", "amount_cents": -900}]))
    assert r.status_code == 422
    assert "zero" in r.json()["detail"]


def test_conta_inexistente_422(client):
    r = client.post("/transactions", json=_tx([
        {"account_code": "9.9", "amount_cents": 1}, {"account_code": "1.01.01", "amount_cents": -1}]))
    assert r.status_code == 422
    assert "9.9" in r.json()["detail"]


def test_conta_que_exige_titulo_422(client):
    r = client.post("/transactions", json=_tx([
        {"account_code": "5.99", "amount_cents": 1000}, {"account_code": "2.02.01", "amount_cents": -1000}]))
    assert r.status_code == 422
    assert "título" in r.json()["detail"]
