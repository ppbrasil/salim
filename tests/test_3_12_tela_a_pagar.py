def test_tela_a_pagar_destaca_atrasadas_e_separa_a_receber(client):
    client.post("/obligations/bills", json={
        "event_date": "2026-08-10", "description": "Luz", "expense_account": "5.01.03", "amount_cents": 10000,
        "due_date": "2026-08-20", "counterparty": "Copel"})
    client.post("/obligations/bills", json={
        "event_date": "2026-08-10", "description": "Internet", "expense_account": "5.01.05", "amount_cents": 12000,
        "due_date": "2026-09-10", "counterparty": "Vivo"})
    client.post("/reimbursable-expenses", json={
        "event_date": "2026-07-22", "description": "Táxi", "expense_account": "5.03.01", "my_share_cents": 3000,
        "other_share_cents": 3000, "counterparty": "Ana", "due_date": "2026-08-01", "payer_account_code": "1.01.01"})
    html = client.get("/ui/payables", params={"today": "2026-08-25"}).text
    assert "Copel" in html and "Vivo" in html
    assert "atrasada" in html and "5 dias" in html           # luz venceu há 5 dias
    assert "R$ 220,00" in html                                # total a pagar: 100 + 120
    assert html.index("Copel") < html.index("Vivo")           # ordenado por vencimento
    assert "Viagem" not in html and "Ana" not in html        # a receber tem tela própria (/ui/receivables)
    assert "Ana" in client.get("/ui/receivables", params={"today": "2026-08-25"}).text
