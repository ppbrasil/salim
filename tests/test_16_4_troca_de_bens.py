"""16.4 Troca de um bem: o que vai trocar, quando, quanto custa um novo e por quanto venderia o usado.
A perda (novo − usado) é o que precisa ser guardado até a troca; vira uma reserva com linha necessária."""
from datetime import date

import pytest

from salim import reserves as rsv

HOJE = date(2026, 11, 21)


def _troca(session, **kw):
    base = dict(name="Carro", kind="replacement", category="carro", new_price_cents=10_000_000, resale_cents=6_000_000,
                target_date=date(2030, 11, 20), start_month=date(2026, 11, 1))
    return rsv.create_reserve(session, **{**base, **kw})


def test_perda_e_aporte_mensal_saem_de_novo_menos_usado_e_do_prazo(session):
    r = _troca(session)                                   # nov/26..nov/30 = 49 meses
    assert (r.target_cents, r.monthly_cents, r.kind) == (4_000_000, 81_633, "goal")
    s = rsv.reserve_status(session, r.id, HOJE)
    assert (s.is_replacement, s.category, s.new_price_cents, s.resale_cents) == (True, "carro", 10_000_000, 6_000_000)
    assert (s.total_months, s.required_cents, s.state) == (49, 0, "em_dia")      # começa agora: nada vencido


def test_bem_ja_comprado_nasce_devendo(session):
    r = _troca(session, start_month=date(2023, 11, 15), target_date=date(2027, 11, 20))     # 49 meses; 36 fechados
    s = rsv.reserve_status(session, r.id, HOJE)
    assert (s.closed_months, s.required_cents) == (36, 2_938_776)        # 4.000.000 × 36/49, para cima
    assert (s.gap_cents, s.state) == (2_938_776, "deficit")


@pytest.mark.parametrize("kw, msg", [
    (dict(new_price_cents=None), "quanto custa um novo"),
    (dict(new_price_cents=0), "quanto custa um novo"),
    (dict(resale_cents=None), "por quanto venderia"),
    (dict(resale_cents=-1), "por quanto venderia"),
    (dict(resale_cents=10_000_000), "nada a guardar"),
    (dict(resale_cents=12_000_000), "nada a guardar"),
    (dict(target_date=None), "quando pretende trocar"),
    (dict(category="barco"), "o que vai trocar"),
])
def test_troca_invalida(session, kw, msg):
    with pytest.raises(rsv.ReserveError, match=msg):
        _troca(session, **kw)


def test_usado_zero_e_aceito_e_a_perda_e_o_preco_inteiro(session):
    assert _troca(session, resale_cents=0).target_cents == 10_000_000


def test_meta_comum_nao_e_troca(session):
    r = rsv.create_reserve(session, name="Viagem", kind="goal", target_cents=100_000, target_date=date(2027, 5, 1),
                           start_month=date(2026, 11, 1))
    s = rsv.reserve_status(session, r.id, HOJE)
    assert (s.is_replacement, s.category, s.new_price_cents) == (False, None, None)


def test_troca_entra_no_resumo_com_as_outras(session):
    _troca(session)
    rsv.create_reserve(session, name="Manutenção", kind="provision", monthly_cents=30_000, start_month=date(2026, 11, 1))
    assert rsv.summary(session, HOJE).monthly_needed_cents == 81_633 + 30_000


def test_api_cria_troca(client):
    r = client.post("/reserves", json={"name": "Celular", "kind": "replacement", "category": "celular",
                                       "new_price_cents": 600_000, "resale_cents": 200_000,
                                       "target_date": "2028-11-20", "start_month": "2026-11-01"})
    assert r.status_code == 201
    j = r.json()
    assert (j["is_replacement"], j["target_cents"], j["category"]) == (True, 400_000, "celular")
    assert client.post("/reserves", json={"name": "X", "kind": "replacement", "category": "celular"}).status_code == 422


# ---- tela
def _form(**kw):
    return {"name": "Meu carro", "kind": "replacement", "category": "carro", "new_price": "100.000,00",
            "resale": "60.000,00", "target_date": "2030-11-20", "start_month": "", **kw}


def test_tela_cadastra_troca_e_mostra_a_conta_em_linguagem_simples(client):
    assert client.post("/ui/reserves", data=_form(), follow_redirects=False).status_code == 303
    html = client.get("/ui/reserves", params={"today": "2026-11-21"}).text
    assert "Meu carro" in html and "troca" in html
    assert "100.000,00" in html and "60.000,00" in html and "40.000,00" in html     # novo, usado, o que se perde
    assert "depreci" not in html.lower()


def test_tela_troca_sem_usado_mostra_erro(client):
    r = client.post("/ui/reserves", data=_form(resale=""))
    assert r.status_code == 422 and "por quanto venderia" in r.text
    r = client.post("/ui/reserves", data=_form(resale="100.000,00"))
    assert r.status_code == 422 and "nada a guardar" in r.text
