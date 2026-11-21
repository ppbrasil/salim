"""16.3 Tela de Reservas: painel "você se deve", uma carta por reserva, cadastro e aporte/uso pelo navegador."""
HOJE = {"today": "2026-11-20"}


def _meta(client, **kw):
    d = {"name": "Viagem", "kind": "goal", "target": "12.000,00", "target_date": "2027-05-31", "start_month": "2026-06-01"}
    return client.post("/ui/reserves", data={**d, **kw}, follow_redirects=False)


def test_tela_vazia_mostra_formularios_e_menu(client):
    html = client.get("/ui/reserves", params=HOJE).text
    assert "Nenhuma reserva" in html and 'name="kind"' in html and "/ui/reserves" in client.get("/ui/budget").text


def test_cadastro_de_meta_e_lista_com_falta_e_atraso(client):
    r = _meta(client)
    assert r.status_code == 303
    html = client.get("/ui/reserves", params=HOJE).text
    assert "Viagem" in html and "Você se deve" in html and "R$ 500,00" not in html
    assert "5.000,00" in html or "R$ 5.000,00" in html          # 5 meses fechados × 1.000,00 sem aporte
    assert "5,0 meses" in html and "em déficit" in html


def test_aporte_pela_tela_atualiza_o_status(client):
    _meta(client)
    rid = client.get("/reserves", params=HOJE).json()["reserves"][0]["id"]
    r = client.post(f"/ui/reserves/{rid}/movements", data={"kind": "aporte", "amount": "5.000,00", "movement_date": "2026-10-01"},
                    follow_redirects=False)
    assert r.status_code == 303
    html = client.get("/ui/reserves", params=HOJE).text
    assert "em dia" in html and "Você se deve" not in html and "Tudo em dia" in html


def test_uso_maior_que_o_saldo_mostra_erro_na_tela(client):
    _meta(client)
    rid = client.get("/reserves", params=HOJE).json()["reserves"][0]["id"]
    r = client.post(f"/ui/reserves/{rid}/movements", data={"kind": "uso", "amount": "10,00", "movement_date": "2026-10-01"})
    assert r.status_code == 422 and "uso maior que o saldo" in r.text


def test_cadastro_invalido_mostra_erro_e_nao_grava(client):
    r = _meta(client, target="abc")
    assert r.status_code == 422 and "valor inválido" in r.text
    r = client.post("/ui/reserves", data={"name": "Carro", "kind": "provision", "monthly": ""})
    assert r.status_code == 422 and "aporte mensal" in r.text
    assert client.get("/reserves").json()["reserves"] == []


def test_provisao_e_arquivar(client):
    client.post("/ui/reserves", data={"name": "Manutenção", "kind": "provision", "monthly": "300,00", "start_month": "2026-05-01"})
    html = client.get("/ui/reserves", params=HOJE).text
    assert "Manutenção" in html and "provisão" in html
    rid = client.get("/reserves", params=HOJE).json()["reserves"][0]["id"]
    assert client.post(f"/ui/reserves/{rid}/archive", follow_redirects=False).status_code == 303
    assert "Nenhuma reserva" in client.get("/ui/reserves", params=HOJE).text
