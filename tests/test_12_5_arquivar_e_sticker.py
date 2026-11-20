"""12.5 Arquivar conta vazia (some das telas, histórico fica) e sticker "Mês atual" nas tabelas mensais."""


def _lanca(client, conta, cents, dia="2026-08-05"):
    client.post("/transactions", json={"event_date": dia, "description": conta, "entries": [
        {"account_code": conta, "amount_cents": cents}, {"account_code": "1.01.01", "amount_cents": -cents}]})


def _codigos(client):
    out = []

    def walk(nodes):
        for n in nodes:
            out.append(n["code"])
            walk(n["children"])
    walk(client.get("/accounts").json())
    return out


def test_arquivar_conta_vazia_some_do_plano_e_do_formulario(client):
    assert client.patch("/accounts/5.01.04", json={"archived": True}).status_code == 200
    assert "5.01.04" not in _codigos(client)
    assert "Água" not in client.get("/ui/accounts").text
    assert "Água" not in client.get("/ui/transactions/new").text


def test_nao_arquiva_conta_com_saldo_nem_grupo_com_filho_ativo(client):
    _lanca(client, "5.01.03", 10000)
    r = client.patch("/accounts/5.01.03", json={"archived": True})
    assert r.status_code == 422 and "saldo" in r.json()["detail"]
    r = client.patch("/accounts/5.01", json={"archived": True})
    assert r.status_code == 422 and "filhas" in r.json()["detail"]


def test_conta_arquivada_com_saldo_zero_continua_no_dre_do_passado(client):
    _lanca(client, "5.01.04", 5000)
    _lanca(client, "1.01.01", 5000, dia="2026-08-06")                       # estorno manual: zera o saldo
    client.post("/transactions", json={"event_date": "2026-08-07", "description": "zera", "entries": [
        {"account_code": "5.01.04", "amount_cents": -5000}, {"account_code": "1.01.01", "amount_cents": 5000}]})
    # saldo agora é zero → pode arquivar sem perder o histórico do DRE
    assert client.get("/accounts/5.01.04/statement").json()[-1]["running_cents"] == 0


def test_desarquivar(client):
    client.patch("/accounts/5.01.04", json={"archived": True})
    client.patch("/accounts/5.01.04", json={"archived": False})
    assert "5.01.04" in _codigos(client)


def test_sticker_mes_atual_no_dre_e_no_caixa(client):
    _lanca(client, "5.02.01", 10000, dia="2026-08-05")
    _lanca(client, "5.02.01", 20000, dia="2026-09-05")
    dre = client.get("/ui/reports/dre", params={"start": "2026-08", "end": "2026-09", "today": "2026-09-10"}).text
    assert dre.count("Mês atual") == 1 and dre.index("ago/26") < dre.index("Mês atual") < dre.index("Total")
    caixa = client.get("/ui/reports/cash", params={"start": "2026-08", "end": "2026-09", "today": "2026-09-10"}).text
    assert caixa.count("Mês atual") == 1
    sem = client.get("/ui/reports/dre", params={"start": "2026-08", "end": "2026-09", "today": "2026-12-10"}).text
    assert "Mês atual" not in sem
