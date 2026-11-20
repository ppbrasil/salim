"""15.1 Planejar o orçamento por linha: editar o valor padrão ao lado da média dos últimos meses."""
from datetime import date

import pytest

from salim import budget as bud
from salim import budgetplan
from salim.chart import seed_chart
from salim.ledger import Entry, post_transaction

HOJE = date(2026, 11, 20)


def _gasta(session, conta, valores, primeiro=date(2026, 5, 1)):
    """Uma despesa por mês a partir de `primeiro` (competência = mês do evento)."""
    for i, v in enumerate(valores):
        m = primeiro.month + i
        post_transaction(session, event_date=date(2026, m, 10), description=f"{conta} {m}",
                         entries=[Entry(conta, v), Entry("1.01.01", -v)])


def _linhas(plano):
    return {l.code: l for g in plano.groups for l in g.lines}


def test_media_dos_ultimos_6_meses_fechados_sem_contar_o_mes_corrente(session):
    seed_chart(session)
    _gasta(session, "5.02.01", [60000, 60000, 60000, 60000, 60000, 90000])           # mai–out
    post_transaction(session, event_date=date(2026, 11, 5), description="nov",
                     entries=[Entry("5.02.01", 999999), Entry("1.01.01", -999999)])  # mês corrente: fora da média
    p = budgetplan.build_plan(session, "expense", HOJE, months=6)
    l = _linhas(p)["5.02.01"]
    assert (p.n_months, l.avg_cents) == (6, 65000)
    assert l.monthly == [60000, 60000, 60000, 60000, 60000, 90000]


def test_mes_sem_historico_nao_dilui_a_media(session):
    seed_chart(session)
    _gasta(session, "5.02.01", [30000, 50000], primeiro=date(2026, 9, 1))             # só set e out
    p = budgetplan.build_plan(session, "expense", HOJE, months=6)
    assert p.n_months == 2 and _linhas(p)["5.02.01"].avg_cents == 40000


def test_sem_nenhum_historico_media_e_zero_e_janela_vazia(session):
    seed_chart(session)
    p = budgetplan.build_plan(session, "expense", HOJE)
    assert p.n_months == 0 and _linhas(p)["5.02.01"].avg_cents == 0


def test_grupo_soma_linhas_e_orcamento_do_grupo_e_a_soma_das_linhas(session):
    seed_chart(session)
    _gasta(session, "5.02.01", [60000] * 6)
    _gasta(session, "5.02.02", [20000] * 6)
    bud.set_budget(session, "5.02.01", 70000)
    bud.set_budget(session, "5.02.02", 15000)
    p = budgetplan.build_plan(session, "expense", HOJE)
    g = next(g for g in p.groups if g.code == "5.02")
    assert (g.avg_cents, g.budget_cents) == (80000, 85000)
    assert g.monthly == [80000] * 6
    assert p.total_budget_cents == 85000
    assert _linhas(p)["5.02.01"].share_pct == 82                     # 70000 / 85000


def test_conta_filha_de_terceiro_nivel_soma_na_linha(session):
    seed_chart(session)
    from salim.ledger import create_account
    from salim.models import AccountType
    create_account(session, code="5.07.03", name="Dívidas", type=AccountType.EXPENSE, parent_code="5.07", is_group=True)
    create_account(session, code="5.07.03.01", name="Juros cheque especial", type=AccountType.EXPENSE, parent_code="5.07.03")
    _gasta(session, "5.07.03.01", [10000] * 6)
    p = budgetplan.build_plan(session, "expense", HOJE)
    assert _linhas(p)["5.07.03"].avg_cents == 10000 and next(g for g in p.groups if g.code == "5.07").avg_cents == 10000


def test_receita_tem_sinal_positivo(session):
    seed_chart(session)
    for m in range(5, 11):
        post_transaction(session, event_date=date(2026, m, 5), description="Salário",
                         entries=[Entry("1.01.01", 500000), Entry("4.01", -500000)])
    p = budgetplan.build_plan(session, "income", HOJE)
    solta = next(g for g in p.groups if g.code == "4.01")
    assert solta.avg_cents == 500000 and not solta.is_group


def test_salvar_define_o_padrao_mantem_perfil_e_ignora_o_que_nao_mudou(session):
    seed_chart(session)
    bud.set_budget(session, "5.01.01", 300000, profile="lump", day_of_month=5)
    n = budgetplan.save_plan(session, {"5.01.01": 320000, "5.02.01": 80000, "5.02.02": None})
    assert n == 2
    a, b = bud.effective_budget(session, "5.01.01", HOJE), bud.effective_budget(session, "5.02.01", HOJE)
    assert (a.amount_cents, a.profile, a.day_of_month) == (320000, "lump", 5)
    assert (b.amount_cents, b.profile) == (80000, "spread")
    assert bud.effective_budget(session, "5.02.02", HOJE) is None
    assert budgetplan.save_plan(session, {"5.01.01": 320000}) == 0       # igual ao que já está


def test_salvar_rejeita_negativo_e_conta_de_outro_tipo(session):
    seed_chart(session)
    with pytest.raises(bud.BudgetError):
        budgetplan.save_plan(session, {"5.02.01": -1})
    with pytest.raises(bud.BudgetError):
        budgetplan.save_plan(session, {"1.01.01": 100})


# ---- tela
def test_tela_planejar_mostra_media_orcamento_e_campos(client):
    for m in range(5, 11):
        client.post("/transactions", json={"event_date": f"2026-{m:02d}-10", "description": "Mercado", "entries": [
            {"account_code": "5.02.01", "amount_cents": 60000}, {"account_code": "1.01.01", "amount_cents": -60000}]})
    html = client.get("/ui/budget/plan", params={"today": "2026-11-20"}).text
    assert "Planejar" in html and "600,00" in html and 'name="b_5.02.01"' in html
    assert "últimos 6 meses" in html and "Receitas" in html and "Despesas" in html
    assert "/ui/budget/plan" in client.get("/ui/budget").text           # abas ligadas


def test_tela_salvar_grava_e_mostra_o_orcamento_na_proxima_visita(client):
    r = client.post("/ui/budget/plan", data={"b_5.02.01": "800,00", "b_5.02.02": "", "b_5.01.01": "3.000,00"},
                    follow_redirects=False)
    assert r.status_code == 303
    html = client.get("/ui/budget/plan", params={"today": "2026-11-20"}).text
    assert 'value="800,00"' in html and 'value="3.000,00"' in html


def test_tela_salvar_valor_invalido_mostra_erro_e_nao_grava(client):
    r = client.post("/ui/budget/plan", data={"b_5.02.01": "800,00", "b_5.02.02": "abc"})
    assert r.status_code == 422 and "valor inválido" in r.text
    assert 'value="800,00"' not in client.get("/ui/budget/plan").text
