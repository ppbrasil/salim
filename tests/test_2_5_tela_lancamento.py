def _form(**kw):
    base = {"date": "2026-11-05", "description": "Aluguel",
            "acc_1": "5.01.01", "deb_1": "3.000,00", "cred_1": "",
            "acc_2": "1.01.01", "deb_2": "", "cred_2": "3000,00",
            "acc_3": "", "deb_3": "", "cred_3": "", "acc_4": "", "deb_4": "", "cred_4": ""}
    base.update(kw)
    return base


def test_formulario_tem_os_campos(client):
    html = client.get("/ui/transactions/new").text
    for campo in ('name="date"', 'name="description"', 'name="acc_1"', 'name="deb_1"', 'name="cred_4"'):
        assert campo in html


def test_posta_e_redireciona(client):
    r = client.post("/ui/transactions", data=_form(), follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/ui/accounts"
    assert client.get("/accounts/5.01.01/statement").json()[0]["delta_cents"] == 300000


def test_erro_aparece_na_tela_e_preserva_o_que_foi_digitado(client):
    r = client.post("/ui/transactions", data=_form(cred_2="2900,00"))
    assert r.status_code == 422
    assert "zero" in r.text and 'value="Aluguel"' in r.text
    assert client.get("/accounts/5.01.01/statement").json() == []   # nada gravado


def test_valor_invalido_aparece_na_tela(client):
    r = client.post("/ui/transactions", data=_form(deb_1="abc"))
    assert r.status_code == 422 and "valor inválido" in r.text
