from datetime import date

import pytest

from salim.bankimport import (
    ImportError_, RawItem, book_item, ignore_item, import_csv, list_items, match_items, sync_connector,
)
from salim.chart import seed_chart
from salim.ledger import Entry, balance, post_transaction
from salim.obligations import register_bill, settle_obligations

CSV_BR = """Data;Descrição;Valor
05/08/2026;MERCADO XYZ;-45,90
06/08/2026;SALARIO ACME;5.000,00
07/08/2026;TARIFA;-12,00
"""


@pytest.fixture(autouse=True)
def _chart(session):
    seed_chart(session)


# ---- 8.1 CSV -> fila
def test_importa_csv_brasileiro_com_sinais(session):
    r = import_csv(session, "1.01.01", CSV_BR)
    assert (r.created, r.skipped, r.errors) == (3, 0, [])
    itens = list_items(session, status="pending")
    assert [(i.date, i.amount_cents, i.description) for i in itens] == [
        (date(2026, 8, 5), -4590, "MERCADO XYZ"), (date(2026, 8, 6), 500000, "SALARIO ACME"), (date(2026, 8, 7), -1200, "TARIFA")]


def test_csv_com_virgula_e_data_iso(session):
    r = import_csv(session, "1.01.01", "date,description,amount\n2026-08-05,Padaria,-18.50\n")
    assert r.created == 1 and list_items(session)[0].amount_cents == -1850


def test_reimportar_o_mesmo_arquivo_nao_duplica_mas_linhas_iguais_do_mesmo_dia_valem(session):
    dobrado = "Data;Descrição;Valor\n05/08/2026;CAFE;-5,00\n05/08/2026;CAFE;-5,00\n"
    assert import_csv(session, "1.01.01", dobrado).created == 2
    r = import_csv(session, "1.01.01", dobrado)
    assert (r.created, r.skipped) == (0, 2) and len(list_items(session)) == 2


def test_linha_invalida_e_reportada_e_o_resto_entra(session):
    r = import_csv(session, "1.01.01", "Data;Descrição;Valor\n05/08/2026;OK;-1,00\nxx;RUIM;-2,00\n06/08/2026;SEM VALOR;abc\n")
    assert r.created == 1 and [e.line for e in r.errors] == [3, 4]


def test_cabecalho_ausente_e_conta_invalida(session):
    with pytest.raises(ImportError_, match="colunas"):
        import_csv(session, "1.01.01", "a;b;c\n1;2;3\n")
    with pytest.raises(ImportError_, match="caixa"):
        import_csv(session, "5.02.01", CSV_BR)


# ---- 8.2 casar com lançamento existente
def test_casa_pagamento_ja_lancado_com_tolerancia_de_dias(session):
    luz = register_bill(session, event_date=date(2026, 8, 1), description="Luz", expense_account="5.01.03",
                        amount_cents=10000, due_date=date(2026, 8, 20))
    pg = settle_obligations(session, event_date=date(2026, 8, 20), items=[(luz.id, None)], cash_account_code="1.01.01")
    import_csv(session, "1.01.01", "Data;Descrição;Valor\n21/08/2026;COPEL;-100,00\n21/08/2026;OUTRO;-77,00\n")
    assert match_items(session) == 1
    casado = list_items(session, status="matched")[0]
    assert casado.description == "COPEL" and casado.transaction_id == pg.id
    assert [i.description for i in list_items(session, status="pending")] == ["OUTRO"]


def test_uma_transacao_nao_casa_com_dois_itens(session):
    post_transaction(session, event_date=date(2026, 8, 5), description="Cafe",
                     entries=[Entry("5.02.02", 500), Entry("1.01.01", -500)])
    import_csv(session, "1.01.01", "Data;Descrição;Valor\n05/08/2026;CAFE;-5,00\n05/08/2026;CAFE;-5,00\n")
    assert match_items(session) == 1 and len(list_items(session, status="pending")) == 1


def test_nao_casa_fora_da_janela_nem_valor_diferente(session):
    post_transaction(session, event_date=date(2026, 8, 1), description="Cafe",
                     entries=[Entry("5.02.02", 500), Entry("1.01.01", -500)])
    import_csv(session, "1.01.01", "Data;Descrição;Valor\n10/08/2026;CAFE;-5,00\n02/08/2026;CAFE;-5,01\n")
    assert match_items(session) == 0


# ---- 8.3 criar lançamento do item
def test_lancar_item_de_saida_e_de_entrada(session):
    import_csv(session, "1.01.01", CSV_BR)
    mercado, salario, _ = list_items(session)
    book_item(session, mercado.id, "5.02.01")
    book_item(session, salario.id, "4.01")
    assert balance(session, "5.02.01") == 4590 and balance(session, "4.01") == 500000
    assert balance(session, "1.01.01") == 500000 - 4590
    assert {i.status for i in list_items(session) if i.id in (mercado.id, salario.id)} == {"booked"}
    assert list_items(session, status="booked")[0].transaction_id is not None


def test_nao_lanca_duas_vezes_nem_item_ja_casado_nem_ignorado(session):
    import_csv(session, "1.01.01", CSV_BR)
    a, b, c = list_items(session)
    book_item(session, a.id, "5.02.01")
    with pytest.raises(ImportError_, match="já tratado"):
        book_item(session, a.id, "5.02.01")
    ignore_item(session, b.id)
    with pytest.raises(ImportError_, match="já tratado"):
        book_item(session, b.id, "4.01")
    assert balance(session, "4.01") == 0


def test_lancar_item_com_conta_invalida_nao_muda_o_item(session):
    import_csv(session, "1.01.01", CSV_BR)
    a = list_items(session)[0]
    with pytest.raises(ImportError_, match="9.9.9"):
        book_item(session, a.id, "9.9.9")
    assert list_items(session, status="pending")[0].id == a.id


# ---- 8.4 contrato do conector
class FakeConnector:
    name = "fake"

    def __init__(self):
        self.calls = []

    def fetch_transactions(self, account_code: str, since: date) -> list[RawItem]:
        self.calls.append((account_code, since))
        return [RawItem(date(2026, 8, 5), -4590, "MERCADO XYZ", external_id="ofx-1"),
                RawItem(date(2026, 8, 6), 500000, "SALARIO ACME", external_id="ofx-2")]


def test_conector_alimenta_a_mesma_fila_sem_duplicar(session):
    c = FakeConnector()
    r = sync_connector(session, c, "1.01.01", since=date(2026, 8, 1))
    assert r.created == 2 and c.calls == [("1.01.01", date(2026, 8, 1))]
    assert sync_connector(session, c, "1.01.01", since=date(2026, 8, 1)).created == 0
    assert len(list_items(session)) == 2
