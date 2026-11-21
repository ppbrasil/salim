"""16.1/16.2 Reservas (conta gráfica): meta e provisão, aportes e usos, linha necessária e status."""
from datetime import date

import pytest

from salim import reserves as rsv

HOJE = date(2026, 11, 20)


def _meta(session, **kw):
    base = dict(name="Viagem", kind="goal", target_cents=1_200_000, target_date=date(2027, 5, 31),
                start_month=date(2026, 6, 1))
    return rsv.create_reserve(session, **{**base, **kw})


def _prov(session, **kw):
    base = dict(name="Manutenção do carro", kind="provision", monthly_cents=30_000, start_month=date(2026, 5, 1))
    return rsv.create_reserve(session, **{**base, **kw})


# ---- cadastro
def test_meta_deriva_o_aporte_mensal_do_alvo_e_do_prazo(session):
    r = _meta(session, start_month=date(2026, 12, 1))        # dez/26..mai/27 = 6 meses
    assert (r.kind, r.monthly_cents, r.start_month) == ("goal", 200_000, date(2026, 12, 1))


def test_meta_arredonda_o_aporte_para_cima(session):
    assert _meta(session, target_cents=1_000_000, start_month=date(2026, 12, 1)).monthly_cents == 166_667


def test_inicio_vira_dia_1_e_padrao_e_o_mes_corrente(session, monkeypatch):
    r = _meta(session, start_month=date(2026, 6, 17))
    assert r.start_month == date(2026, 6, 1)
    monkeypatch.setattr("salim.reserves.clock_today", lambda: HOJE)
    assert _prov(session, name="B", start_month=None).start_month == date(2026, 11, 1)


@pytest.mark.parametrize("kw, msg", [
    (dict(name="  "), "nome"),
    (dict(kind="outra"), "tipo"),
    (dict(target_cents=0), "valor-alvo"),
    (dict(target_date=None), "data-alvo"),
    (dict(target_date=date(2026, 5, 31)), "antes do início"),
])
def test_meta_invalida(session, kw, msg):
    with pytest.raises(rsv.ReserveError, match=msg):
        _meta(session, **kw)


def test_provisao_exige_aporte_mensal_e_nome_unico(session):
    with pytest.raises(rsv.ReserveError, match="aporte mensal"):
        _prov(session, monthly_cents=0)
    _prov(session)
    with pytest.raises(rsv.ReserveError, match="já existe"):
        _prov(session)


def test_meta_ignora_aporte_mensal_informado(session):
    assert _meta(session, monthly_cents=1, start_month=date(2026, 12, 1)).monthly_cents == 200_000


# ---- aportes e usos
def test_aporte_e_uso_movem_o_saldo(session):
    r = _prov(session)
    rsv.add_movement(session, r.id, kind="aporte", amount_cents=100_000, movement_date=date(2026, 10, 5))
    rsv.add_movement(session, r.id, kind="uso", amount_cents=40_000, movement_date=date(2026, 10, 20), note="pastilha")
    s = rsv.reserve_status(session, r.id, HOJE)
    assert (s.funded_cents, s.used_cents, s.balance_cents) == (100_000, 40_000, 60_000)


def test_movimento_invalido(session):
    r = _prov(session)
    rsv.add_movement(session, r.id, kind="aporte", amount_cents=10_000, movement_date=HOJE)
    for kw, msg in [(dict(kind="aporte", amount_cents=0), "maior que zero"), (dict(kind="x", amount_cents=1), "tipo"),
                    (dict(kind="uso", amount_cents=10_001), "saldo")]:
        with pytest.raises(rsv.ReserveError, match=msg):
            rsv.add_movement(session, r.id, movement_date=HOJE, **kw)
    with pytest.raises(rsv.ReserveError, match="não existe"):
        rsv.add_movement(session, 999, kind="aporte", amount_cents=1, movement_date=HOJE)


def test_reserva_arquivada_nao_recebe_movimento_e_sai_do_resumo(session):
    r = _prov(session)
    rsv.archive_reserve(session, r.id)
    with pytest.raises(rsv.ReserveError, match="arquivada"):
        rsv.add_movement(session, r.id, kind="aporte", amount_cents=1, movement_date=HOJE)
    assert rsv.summary(session, HOJE).reserves == []


# ---- linha necessária e status
@pytest.mark.parametrize("aportes, necessario, atraso, estado", [
    (300_000, 500_000, 2.0, "deficit"),        # 5 meses fechados × 100.000; faltam 2 meses de aporte
    (450_000, 500_000, 0.5, "atencao"),
    (480_000, 500_000, 0.2, "em_dia"),
    (500_000, 500_000, 0.0, "em_dia"),
    (900_000, 500_000, 0.0, "em_dia"),         # adiantado
])
def test_meta_status_pela_linha_reta(session, aportes, necessario, atraso, estado):
    r = _meta(session)                         # jun/26..mai/27 = 12 meses; 100.000/mês; jun..out fechados = 5
    rsv.add_movement(session, r.id, kind="aporte", amount_cents=aportes, movement_date=date(2026, 10, 1))
    s = rsv.reserve_status(session, r.id, HOJE)
    assert (s.monthly_cents, s.closed_months, s.total_months) == (100_000, 5, 12)
    assert (s.required_cents, s.months_behind, s.state) == (necessario, atraso, estado)
    assert s.gap_cents == max(0, necessario - aportes)


def test_mes_corrente_nao_conta_na_linha(session):
    r = _meta(session, start_month=date(2026, 11, 1))
    s = rsv.reserve_status(session, r.id, HOJE)
    assert (s.closed_months, s.required_cents, s.state) == (0, 0, "em_dia")


def test_provisao_acumula_sem_teto_e_uso_nao_cria_deficit(session):
    r = _prov(session)                         # mai..out = 6 meses × 30.000
    rsv.add_movement(session, r.id, kind="aporte", amount_cents=100_000, movement_date=date(2026, 10, 1))
    rsv.add_movement(session, r.id, kind="uso", amount_cents=50_000, movement_date=date(2026, 10, 2))
    s = rsv.reserve_status(session, r.id, HOJE)
    assert (s.required_cents, s.gap_cents, s.months_behind, s.state) == (180_000, 80_000, 2.7, "deficit")
    assert s.balance_cents == 50_000


def test_meta_vencida_e_incompleta_cobra_o_alvo_inteiro(session):
    r = _meta(session, start_month=date(2026, 1, 1), target_date=date(2026, 6, 30))
    rsv.add_movement(session, r.id, kind="aporte", amount_cents=400_000, movement_date=date(2026, 3, 1))
    s = rsv.reserve_status(session, r.id, HOJE)
    assert (s.closed_months, s.required_cents, s.gap_cents, s.months_left) == (6, 1_200_000, 800_000, 0)


def test_resumo_soma_deficits_e_calcula_o_aporte_para_zerar(session):
    a = _meta(session)
    b = _prov(session)
    c = _prov(session, name="IPVA", monthly_cents=10_000)
    rsv.add_movement(session, a.id, kind="aporte", amount_cents=300_000, movement_date=date(2026, 10, 1))   # gap 200.000
    rsv.add_movement(session, b.id, kind="aporte", amount_cents=100_000, movement_date=date(2026, 10, 1))   # gap 80.000
    rsv.add_movement(session, c.id, kind="aporte", amount_cents=70_000, movement_date=date(2026, 10, 1))    # 60.000 necessário: folga
    s = rsv.summary(session, HOJE)
    assert s.total_gap_cents == 280_000
    assert s.monthly_needed_cents == 100_000 + 30_000 + 10_000
    assert s.catch_up_12m_cents == 23_334                       # 280.000 / 12, para cima
    assert s.worst.name == "Manutenção do carro" and s.in_deficit == 2      # o mais atrasado em meses (2,7 × 2,0)
    assert s.total_balance_cents == 470_000


def test_resumo_vazio(session):
    s = rsv.summary(session, HOJE)
    assert (s.total_gap_cents, s.monthly_needed_cents, s.worst, s.in_deficit) == (0, 0, None, 0)


def test_meta_vencida_nao_entra_no_aporte_mensal_necessario(session):
    _meta(session, start_month=date(2026, 1, 1), target_date=date(2026, 6, 30))
    assert rsv.summary(session, HOJE).monthly_needed_cents == 0


# ---- API
def test_api_cria_lista_e_movimenta(client):
    r = client.post("/reserves", json={"name": "Viagem", "kind": "goal", "target_cents": 1_200_000,
                                       "target_date": "2027-05-31", "start_month": "2026-06-01"})
    assert r.status_code == 201 and r.json()["monthly_cents"] == 100_000
    rid = r.json()["id"]
    m = client.post(f"/reserves/{rid}/movements", json={"kind": "aporte", "amount_cents": 300_000, "movement_date": "2026-10-01"})
    assert m.status_code == 201
    j = client.get("/reserves", params={"today": "2026-11-20"}).json()
    assert j["summary"]["total_gap_cents"] == 200_000
    assert j["reserves"][0]["state"] == "deficit" and j["reserves"][0]["balance_cents"] == 300_000


def test_api_erros(client):
    assert client.post("/reserves", json={"name": "x", "kind": "provision", "monthly_cents": 0}).status_code == 422
    assert client.post("/reserves/999/movements", json={"kind": "aporte", "amount_cents": 1, "movement_date": "2026-10-01"}).status_code == 404
