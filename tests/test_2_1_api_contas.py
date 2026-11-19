def _find(nodes, code):
    for n in nodes:
        if n["code"] == code:
            return n
        achado = _find(n["children"], code)
        if achado:
            return achado


def test_lista_plano_de_contas_em_arvore(client):
    r = client.get("/accounts")
    assert r.status_code == 200
    arvore = r.json()
    assert [n["code"] for n in arvore] == ["1", "2", "3", "4", "5"]
    aluguel = _find(arvore, "5.01.01")
    assert aluguel["name"] == "Aluguel" and aluguel["balance_cents"] == 0 and aluguel["children"] == []
    assert _find(arvore, "1.01.01")["is_cash"] is True


def test_saldos_aparecem_e_grupos_somam_filhos(client):
    client.post("/transactions", json={
        "event_date": "2026-11-05", "description": "Aluguel",
        "entries": [{"account_code": "5.01.01", "amount_cents": 300000},
                    {"account_code": "1.01.01", "amount_cents": -300000}]})
    arvore = client.get("/accounts").json()
    assert _find(arvore, "5.01.01")["balance_cents"] == 300000
    assert _find(arvore, "5.01")["balance_cents"] == 300000
    assert _find(arvore, "5")["balance_cents"] == 300000
    assert _find(arvore, "1.01.01")["balance_cents"] == -300000
