def _dados(client):
    client.post("/transactions", json={"event_date": "2026-08-05", "description": "Salário", "entries": [
        {"account_code": "1.01.01", "amount_cents": 500000}, {"account_code": "4.01", "amount_cents": -500000}]})
    client.post("/obligations/bills", json={"event_date": "2026-08-10", "description": "Luz", "expense_account": "5.01.03",
                                            "amount_cents": 10000, "due_date": "2026-09-20", "counterparty": "Copel"})
    client.post("/transactions", json={"event_date": "2026-08-06", "description": "Mercado", "entries": [
        {"account_code": "5.02.01", "amount_cents": 60000}, {"account_code": "1.01.01", "amount_cents": -60000}]})


def test_api_dre(client):
    _dados(client)
    r = client.get("/reports/dre", params={"start": "2026-08-01"}).json()
    assert r["income_cents"] == 500000 and r["expense_cents"] == 70000 and r["result_cents"] == 430000
    assert {l["code"]: l["amount_cents"] for l in r["lines"]} == {"4.01": 500000, "5.01.03": 10000, "5.02.01": 60000}


def test_api_caixa_executado_e_futuro(client):
    _dados(client)
    r = client.get("/reports/cash", params={"start": "2026-08-01", "end": "2026-09-01"}).json()
    assert [(m["month"], m["inflow_cents"], m["outflow_cents"]) for m in r] == [("2026-08", 500000, 60000), ("2026-09", 0, 0)]
    f = client.get("/reports/cash-future", params={"today": "2026-08-12", "months": 2}).json()
    assert [(m["month"], m["outflow_cents"], m["closing_cents"]) for m in f] == [("2026-08", 0, 440000), ("2026-09", 10000, 430000)]


def test_api_orcamento_definir_e_consultar(client):
    _dados(client)
    r = client.put("/budget", json={"account_code": "5.02.01", "amount_cents": 90000})
    assert r.status_code == 200
    r = client.put("/budget", json={"account_code": "5.01.01", "amount_cents": 200000, "profile": "lump", "day_of_month": 5})
    assert r.status_code == 200
    s = client.get("/budget", params={"month": "2026-08-01", "today": "2026-08-10"}).json()
    mercado = next(l for l in s if l["code"] == "5.02.01")
    assert (mercado["actual_cents"], mercado["alert"]) == (60000, "acima_do_ritmo")


def test_api_orcamento_erro_vira_422(client):
    r = client.put("/budget", json={"account_code": "1.01.01", "amount_cents": 1})
    assert r.status_code == 422 and "despesa" in r.json()["detail"]


def test_tela_dre(client):
    _dados(client)
    html = client.get("/ui/reports/dre", params={"start": "2026-08-01"}).text
    assert "Luz" in html and "R$ 5.000,00" in html and "R$ 4.300,00" in html and "Resultado" in html


def test_tela_caixa_mostra_executado_e_projetado(client):
    _dados(client)
    html = client.get("/ui/reports/cash", params={"today": "2026-08-12"}).text
    assert "Executado" in html and "Projetado" in html and "R$ 4.400,00" in html


def test_tela_orcamento_com_formulario_e_alerta(client):
    _dados(client)
    r = client.post("/ui/budget", data={"account_code": "5.02.01", "amount": "900,00", "profile": "spread",
                                        "day_of_month": ""}, follow_redirects=False)
    assert r.status_code == 303
    html = client.get("/ui/budget", params={"month": "2026-08-01", "today": "2026-08-10"}).text
    assert "Supermercado" in html and "acima do ritmo" in html and "R$ 900,00" in html


def test_tela_orcamento_erro_mantem_formulario(client):
    r = client.post("/ui/budget", data={"account_code": "1.01.01", "amount": "10,00", "profile": "spread"})
    assert r.status_code == 422 and "despesa ou receita" in r.text
