def _post(client, d, desc, a, b, v, comp=None):
    e1 = {"account_code": a, "amount_cents": v}
    if comp:
        e1["competence"] = comp
    return client.post("/transactions", json={"event_date": d, "description": desc,
                                              "entries": [e1, {"account_code": b, "amount_cents": -v}]})


def test_extrato_com_saldo_corrente_e_competencia(client):
    _post(client, "2026-11-01", "Salário", "1.01.01", "4.01", 500000)
    _post(client, "2026-11-05", "Aluguel", "5.01.01", "1.01.01", 300000, comp="2026-10-20")
    r = client.get("/accounts/1.01.01/statement")
    assert r.status_code == 200
    linhas = r.json()
    assert [(l["description"], l["delta_cents"], l["running_cents"]) for l in linhas] == [
        ("Salário", 500000, 500000), ("Aluguel", -300000, 200000)]
    desp = client.get("/accounts/5.01.01/statement").json()
    assert desp[0]["competence"] == "2026-10-01"


def test_extrato_de_grupo_soma_subarvore(client):
    _post(client, "2026-11-05", "Aluguel", "5.01.01", "1.01.01", 300000)
    _post(client, "2026-11-10", "Luz", "5.01.03", "1.01.01", 20000)
    linhas = client.get("/accounts/5.01/statement").json()
    assert [l["running_cents"] for l in linhas] == [300000, 320000]


def test_extrato_de_conta_inexistente_404(client):
    assert client.get("/accounts/9.9/statement").status_code == 404
