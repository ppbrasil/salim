def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_partida_sem_seed_nao_cria_plano_de_contas():
    from conftest import new_factory
    from salim.app import create_app
    from salim.models import Account
    sf = new_factory()
    create_app(sf, seed=False)
    with sf() as s:
        assert s.query(Account).count() == 0
    create_app(sf)          # padrão continua semeando (SQLite/dev)
    with sf() as s:
        assert s.query(Account).count() > 0
