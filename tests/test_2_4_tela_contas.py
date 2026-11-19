def _lanca(client):
    client.post("/transactions", json={
        "event_date": "2026-11-05", "description": "Aluguel",
        "entries": [{"account_code": "5.01.01", "amount_cents": 300000},
                    {"account_code": "1.01.01", "amount_cents": -300000}]})


def test_raiz_redireciona_para_o_plano_de_contas(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == "/ui/accounts"


def test_tela_mostra_contas_e_saldos_em_reais(client):
    _lanca(client)
    r = client.get("/ui/accounts")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    html = r.text
    assert "Aluguel" in html and "Conta Corrente" in html
    assert "R$ 3.000,00" in html          # despesa de aluguel e grupos acima dela
    assert "-R$ 3.000,00" in html         # conta corrente ficou negativa
    assert 'href="/ui/accounts/5.01.01"' in html
    assert 'href="/ui/transactions/new"' in html   # menu
