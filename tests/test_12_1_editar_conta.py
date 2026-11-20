"""12.1 Renomear e mover conta entre grupos (partidas apontam para o id, então nada se perde)."""


def _codes(client):
    out = {}

    def walk(nodes, pai=None):
        for n in nodes:
            out[n["code"]] = (n["name"], pai)
            walk(n["children"], n["code"])
    walk(client.get("/accounts").json())
    return out


def test_mover_conta_para_outro_grupo_e_trocar_codigo(client):
    client.post("/accounts", json={"code": "5.06.01", "name": "Multas de Trânsito", "type": "expense", "parent_code": "5.06"})
    client.post("/transactions", json={"event_date": "2026-08-05", "description": "Multa", "entries": [
        {"account_code": "5.06.01", "amount_cents": 13016}, {"account_code": "1.01.01", "amount_cents": -13016}]})
    r = client.patch("/accounts/5.06.01", json={"parent_code": "5.03", "new_code": "5.03.05"})
    assert r.status_code == 200 and r.json()["code"] == "5.03.05"
    contas = _codes(client)
    assert contas["5.03.05"] == ("Multas de Trânsito", "5.03") and "5.06.01" not in contas
    # o histórico acompanha a conta
    extrato = client.get("/accounts/5.03.05/statement").json()
    assert [l["delta_cents"] for l in extrato] == [13016]
    # o DRE passa a somar no grupo novo
    dre = client.get("/reports/dre", params={"start": "2026-08-01", "end": "2026-08-31"}).json()
    assert {l["code"]: l["amount_cents"] for l in dre["lines"]} == {"5.03.05": 13016}


def test_renomear(client):
    r = client.patch("/accounts/5.99", json={"name": "Outros (a classificar)"})
    assert r.status_code == 200 and _codes(client)["5.99"][0] == "Outros (a classificar)"


def test_erros_viram_422_ou_404(client):
    assert client.patch("/accounts/9.99", json={"name": "x"}).status_code == 404
    assert client.patch("/accounts/5.99", json={"new_code": "5.01.01"}).status_code == 409   # código já existe
    assert client.patch("/accounts/5.99", json={"parent_code": "5.02.01"}).status_code == 422  # pai não é grupo
    assert client.patch("/accounts/5.03", json={"parent_code": "5.03.01"}).status_code == 422  # ciclo: filho do próprio filho
    assert client.patch("/accounts/5.99", json={"parent_code": "1.01"}).status_code == 422      # tipo diferente (ativo)
