def test_extrato_com_competencia_e_saldo(client):
    client.post("/transactions", json={
        "event_date": "2026-11-05", "description": "Aluguel",
        "entries": [{"account_code": "5.01.01", "amount_cents": 300000, "competence": "2026-10-20"},
                    {"account_code": "1.01.01", "amount_cents": -300000}]})
    html = client.get("/ui/accounts/5.01.01").text
    assert "Aluguel" in html and "05/11/2026" in html
    assert "out/2026" in html and "R$ 3.000,00" in html


def test_extrato_de_conta_inexistente_404(client):
    assert client.get("/ui/accounts/9.9").status_code == 404
