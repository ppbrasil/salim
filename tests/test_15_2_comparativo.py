"""15.2 Comparativo simples: fatia de cada grupo no gasto, contra a média das famílias brasileiras (IBGE, POF 2017-18)."""
from datetime import date

from salim import benchmark, budgetplan
from salim import budget as bud
from salim.chart import seed_chart
from salim.ledger import Entry, post_transaction

HOJE = date(2026, 11, 20)


def test_posicao_abaixo_na_media_acima():
    assert benchmark.position(1000, 3660).label == "abaixo da média"       # 10% vs 36,6%
    assert benchmark.position(3660, 3660).label == "na média"
    assert benchmark.position(3000, 3660).label == "na média"              # dentro de ±25%
    assert benchmark.position(5500, 3660).label == "acima da média"


def test_referencia_por_nome_do_grupo_ignora_acento_e_caixa():
    assert benchmark.reference_bps("Moradia") == benchmark.reference_bps("HABITAÇÃO") == 3660
    assert benchmark.reference_bps("Alimentação") == 1750
    assert benchmark.reference_bps("Transporte") == 1810
    assert benchmark.reference_bps("Saúde") == 800
    assert benchmark.reference_bps("Lazer") is None
    assert benchmark.reference_bps("Meu grupo") is None


def test_plano_traz_comparativo_so_nos_grupos_com_referencia_usando_o_orcamento(session):
    seed_chart(session)
    bud.set_budget(session, "5.01.01", 360000)      # Moradia
    bud.set_budget(session, "5.02.01", 175000)      # Alimentação
    bud.set_budget(session, "5.05.01", 465000)      # Lazer (sem referência)
    p = budgetplan.build_plan(session, "expense", HOJE)
    g = {x.code: x for x in p.groups}
    assert (g["5.01"].peer.user_pct, g["5.01"].peer.label, g["5.01"].peer.ref_pct) == (36.0, "na média", 36.6)   # 3600/10000
    assert g["5.05"].peer is None
    assert g["5.02"].peer.user_pct == 17.5 and g["5.02"].peer.basis == "orçamento"


def test_sem_orcamento_usa_a_fatia_da_media_gasta(session):
    seed_chart(session)
    for conta, v in (("5.01.01", 70000), ("5.02.01", 30000)):
        for m in range(5, 11):
            post_transaction(session, event_date=date(2026, m, 10), description="x",
                             entries=[Entry(conta, v), Entry("1.01.01", -v)])
    p = budgetplan.build_plan(session, "expense", HOJE)
    g = {x.code: x for x in p.groups}
    assert g["5.01"].peer.basis == "gasto" and g["5.01"].peer.user_pct == 70.0
    assert g["5.01"].peer.label == "acima da média" and g["5.02"].peer.label == "acima da média"   # 30% vs 17,5%


def test_receitas_nao_tem_comparativo(session):
    seed_chart(session)
    p = budgetplan.build_plan(session, "income", HOJE)
    assert all(g.peer is None for g in p.groups)


def test_tela_mostra_o_comparativo_e_a_fonte(client):
    client.post("/ui/budget/plan", data={"b_5.01.01": "3.600,00", "b_5.02.01": "1.750,00", "b_5.03.01": "1.810,00"})
    html = client.get("/ui/budget/plan", params={"today": "2026-11-20"}).text
    assert "famílias brasileiras" in html and "IBGE" in html and "POF 2017-18" in html
    assert "na média" in html or "abaixo da média" in html or "acima da média" in html
