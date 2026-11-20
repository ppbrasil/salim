"""14.1 Configurações do plano de contas: dois níveis (grupo e linha) para despesa e receita, edição pela tela."""
from datetime import date

import pytest

from salim import chartcfg
from salim.chart import seed_chart
from salim.ledger import InvalidAccountError, Entry, get_account, post_transaction


def _seed(session):
    seed_chart(session)


def test_grupo_novo_recebe_o_proximo_codigo_do_tipo(session):
    _seed(session)
    g = chartcfg.create_group(session, "expense", "Educação")
    assert (g.code, g.name, g.is_group, g.type.value) == ("5.08", "Educação", True, "expense")
    r = chartcfg.create_group(session, "income", "Trabalho")
    assert (r.code, r.type.value, r.parent_id == get_account(session, "4").id) == ("4.03", "income", True)


def test_codigo_novo_pula_o_99_reservado_para_outras(session):
    _seed(session)
    assert chartcfg.create_group(session, "expense", "Pets").code == "5.08"       # 5.99 não puxa a numeração


def test_linha_nova_entra_no_grupo_com_codigo_proprio_e_tipo_do_grupo(session):
    _seed(session)
    a = chartcfg.create_line(session, "5.02", "Padaria")
    b = chartcfg.create_line(session, "5.02", "Feira")
    assert (a.code, b.code) == ("5.02.03", "5.02.04") and not a.is_group and a.type.value == "expense"


def test_so_dois_niveis_linha_nao_nasce_em_linha_nem_na_raiz_nem_em_outro_tipo(session):
    _seed(session)
    for pai in ("5.02.01", "5", "2.01"):
        with pytest.raises(InvalidAccountError):
            chartcfg.create_line(session, pai, "Qualquer")


def test_nome_vazio_ou_repetido_no_mesmo_pai_e_barrado(session):
    _seed(session)
    with pytest.raises(InvalidAccountError):
        chartcfg.create_line(session, "5.02", "  ")
    with pytest.raises(InvalidAccountError):
        chartcfg.create_line(session, "5.02", "supermercado")                      # já existe (sem diferenciar caixa)
    with pytest.raises(InvalidAccountError):
        chartcfg.create_group(session, "expense", "Moradia")
    assert chartcfg.create_line(session, "5.03", "Supermercado")                   # em outro grupo pode


def test_mover_linha_para_outro_grupo_leva_o_historico(session):
    _seed(session)
    post_transaction(session, event_date=date(2026, 8, 5), description="Mercado",
                     entries=[Entry("5.02.01", 5000), Entry("1.01.01", -5000)])
    chartcfg.move_line(session, "5.02.01", "5.05")
    assert get_account(session, "5.02.01").parent_id == get_account(session, "5.05").id
    arvore = {g.code: g for g in chartcfg.settings_tree(session, "expense")}
    assert "5.02.01" in [l.code for l in arvore["5.05"].lines]
    assert "5.02.01" not in [l.code for l in arvore["5.02"].lines]


def test_mover_exige_linha_e_grupo_do_mesmo_tipo(session):
    _seed(session)
    with pytest.raises(InvalidAccountError):
        chartcfg.move_line(session, "5.02", "5.05")                    # grupo não se move como linha
    with pytest.raises(InvalidAccountError):
        chartcfg.move_line(session, "5.02.01", "4")                    # outro tipo
    with pytest.raises(InvalidAccountError):
        chartcfg.move_line(session, "5.02.01", "5.03.01")              # destino não é grupo


def test_arvore_de_configuracao_traz_grupos_linhas_e_se_tem_lancamento(session):
    _seed(session)
    post_transaction(session, event_date=date(2026, 8, 5), description="Mercado",
                     entries=[Entry("5.02.01", 5000), Entry("1.01.01", -5000)])
    arvore = {g.code: g for g in chartcfg.settings_tree(session, "expense")}
    assert [l.code for l in arvore["5.02"].lines] == ["5.02.01", "5.02.02"]
    assert {l.code: l.has_postings for l in arvore["5.02"].lines} == {"5.02.01": True, "5.02.02": False}
    assert arvore["5.99"].is_group is False                            # linha solta no primeiro nível
    receitas = chartcfg.settings_tree(session, "income")
    assert [g.code for g in receitas] == ["4.01", "4.02"] and all(not g.is_group for g in receitas)


def test_arquivadas_somem_da_arvore(session):
    _seed(session)
    chartcfg.archive(session, "5.01.04")
    assert "5.01.04" not in [l.code for g in chartcfg.settings_tree(session, "expense") for l in g.lines]


# ---- API e tela
def test_api_cria_grupo_linha_e_move(client):
    g = client.post("/chart/groups", json={"type": "expense", "name": "Educação"})
    assert g.status_code == 201 and g.json()["code"] == "5.08"
    l = client.post("/chart/lines", json={"group_code": "5.08", "name": "Cursos"})
    assert l.status_code == 201 and l.json()["code"] == "5.08.01"
    assert client.post("/chart/lines", json={"group_code": "5.08.01", "name": "x"}).status_code == 422
    assert client.post("/chart/5.08.01/move", json={"group_code": "5.05"}).status_code == 200
    assert client.post("/chart/9.99/move", json={"group_code": "5.05"}).status_code == 422


def test_tela_de_configuracoes_lista_grupos_e_linhas_de_despesa_e_receita(client):
    html = client.get("/ui/settings").text
    for texto in ("Configurações", "Despesas", "Receitas", "Moradia", "Aluguel", "Salário", "Novo grupo"):
        assert texto in html


def test_tela_cria_renomeia_move_e_arquiva(client):
    post = lambda url, **d: client.post(url, data=d, follow_redirects=False)
    assert post("/ui/settings/groups", type="expense", name="Educação").status_code == 303
    assert post("/ui/settings/lines", group_code="5.08", name="Cursos").status_code == 303
    assert post("/ui/settings/rename", code="5.08.01", name="Cursos online").status_code == 303
    assert post("/ui/settings/move", code="5.08.01", group_code="5.05").status_code == 303
    html = client.get("/ui/settings").text
    assert "Cursos online" in html
    assert post("/ui/settings/archive", code="5.08.01").status_code == 303
    assert "Cursos online" not in client.get("/ui/settings").text


def test_tela_mostra_o_erro_e_nao_altera(client):
    r = client.post("/ui/settings/lines", data={"group_code": "5.02", "name": "Supermercado"})
    assert r.status_code == 422 and "já existe" in r.text
    client.post("/transactions", json={"event_date": "2026-08-05", "description": "Aluguel", "entries": [
        {"account_code": "5.01.01", "amount_cents": 100000}, {"account_code": "1.01.01", "amount_cents": -100000}]})
    r = client.post("/ui/settings/archive", data={"code": "5.01.01"})
    assert r.status_code == 422 and "tem saldo" in r.text            # conta com saldo não arquiva
