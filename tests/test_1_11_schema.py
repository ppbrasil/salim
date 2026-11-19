import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


def _nomes(session) -> set[str]:
    """Tabelas, views e triggers existentes, no dialeto do banco de teste."""
    if session.get_bind().dialect.name == "sqlite":
        return {r[0] for r in session.execute(text("select name from sqlite_master")).all()}
    return {r[0] for r in session.execute(text(
        "select table_name from information_schema.tables where table_schema = 'public' "
        "union select tgname from pg_trigger where not tgisinternal")).all()}


def test_schema_tem_tabelas_views_e_triggers(session):
    nomes = _nomes(session)
    for n in ["accounts", "transactions", "postings", "obligations", "budget_lines", "import_items",
              "v_obligation_balance", "v_dre", "v_cash_executed", "v_cash_future", "trg_posting_rules",
              "trg_postings_no_update", "trg_tx_no_delete", "trg_obl_frozen_cols", "trg_obl_no_delete"]:
        assert n in nomes, n


def test_chaves_estrangeiras_ligadas(session):
    """Comportamento, não configuração: partida apontando para lançamento e conta inexistentes é recusada."""
    with pytest.raises(IntegrityError):
        session.execute(text(
            "insert into postings (transaction_id, account_id, amount_cents, competence_month) "
            "values (999999, 999999, 100, :m)"), {"m": "2026-01-01"})
    session.rollback()
