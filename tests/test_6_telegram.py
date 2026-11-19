from datetime import date

import pytest

from salim.budget import set_budget
from salim.chart import seed_chart
from salim.ledger import Entry, balance, post_transaction
from salim.obligations import register_bill
from salim.telegram import Bot

DONO = 111
HOJE = date(2026, 8, 12)


def msg(texto, update_id=1, chat=DONO):
    return {"update_id": update_id, "message": {"message_id": update_id, "chat": {"id": chat},
                                                 "from": {"id": chat}, "text": texto}}


@pytest.fixture
def bot(session, ctx_factory):
    seed_chart(session)
    return Bot(ctx_factory, allowed_ids={DONO}, clock=lambda: HOJE)


_seq = iter(range(1000, 10**6))


def falar(bot, texto, update_id=None, chat=DONO):
    """Cada chamada é um update novo, a menos que o teste fixe o update_id (reenvio)."""
    update_id = next(_seq) if update_id is None else update_id
    return [r.text for r in bot.handle(msg(texto, update_id, chat))]


def _gasto(session, conta, valor, dia=5):
    post_transaction(session, event_date=date(2026, 8, dia), description=conta,
                     entries=[Entry(conta, valor), Entry("1.01.01", -valor)])


# ---- 6.1 /saldo
def test_saldo_sem_argumento_lista_o_caixa(bot, session):
    post_transaction(session, event_date=date(2026, 8, 1), description="Salário",
                     entries=[Entry("1.01.01", 500000), Entry("4.01", -500000)])
    [resp] = falar(bot, "/saldo")
    assert "Conta Corrente" in resp and "R$ 5.000,00" in resp and "Total" in resp


def test_saldo_de_uma_conta(bot, session):
    _gasto(session, "5.02.01", 4500)
    assert "Supermercado" in falar(bot, "/saldo 5.02.01")[0] and "R$ 45,00" in falar(bot, "/saldo 5.02.01")[0]


def test_saldo_conta_inexistente_e_comando_desconhecido(bot):
    assert "não encontrei" in falar(bot, "/saldo 9.9.9")[0].lower()
    assert "/saldo" in falar(bot, "bom dia")[0] and "/orcamento" in falar(bot, "/ajuda")[0]


# ---- 6.2 autorização
def test_chat_nao_autorizado_nao_recebe_resposta(bot):
    assert falar(bot, "/saldo", chat=999) == []


def test_lista_vazia_nega_todos(session, ctx_factory):
    seed_chart(session)
    assert Bot(ctx_factory, allowed_ids=set(), clock=lambda: HOJE).handle(msg("/saldo")) == []


def test_update_sem_texto_e_ignorado(bot):
    assert bot.handle({"update_id": 5, "message": {"chat": {"id": DONO}, "from": {"id": DONO}, "photo": []}}) == []
    assert bot.handle({"update_id": 6}) == []


# ---- 6.3 /orcamento e /faturas
def test_orcamento_mostra_gasto_meta_e_alerta(bot, session):
    set_budget(session, "5.02.01", 90000)
    _gasto(session, "5.02.01", 60000)
    [resp] = falar(bot, "/orcamento")
    assert "Supermercado" in resp and "R$ 600,00" in resp and "R$ 900,00" in resp and "66%" in resp and "acima do ritmo" in resp


def test_orcamento_vazio(bot):
    assert "nenhuma meta" in falar(bot, "/orcamento")[0].lower()


def test_faturas_lista_a_pagar_por_vencimento(bot, session):
    register_bill(session, event_date=date(2026, 7, 1), description="Luz", expense_account="5.01.03", amount_cents=10000,
                  due_date=date(2026, 8, 8), counterparty="Copel")
    register_bill(session, event_date=date(2026, 8, 1), description="Internet", expense_account="5.01.05",
                  amount_cents=12000, due_date=date(2026, 8, 20), counterparty="Vivo")
    [resp] = falar(bot, "/faturas")
    assert resp.index("Copel") < resp.index("Vivo")
    assert "atrasada" in resp and "4 dias" in resp and "20/08" in resp and "R$ 220,00" in resp


def test_faturas_nada_a_pagar(bot):
    assert "nada" in falar(bot, "/faturas")[0].lower()


# ---- 6.4 lançamento com confirmação
def test_lancar_propoe_e_so_grava_ao_confirmar(bot, session):
    [prop] = falar(bot, "/lancar 45,90 5.02.01 1.01.01 Mercado", update_id=10)
    assert "R$ 45,90" in prop and "Supermercado" in prop and "/ok" in prop
    assert balance(session, "5.02.01") == 0
    [ok] = falar(bot, "/ok", update_id=11)
    assert "registrado" in ok.lower() and balance(session, "5.02.01") == 4590


def test_cancelar_descarta_a_proposta(bot, session):
    falar(bot, "/lancar 10,00 5.02.01 1.01.01 Teste", update_id=10)
    assert "cancel" in falar(bot, "/cancelar", update_id=11)[0].lower()
    assert "nada pendente" in falar(bot, "/ok", update_id=12)[0].lower()
    assert balance(session, "5.02.01") == 0


def test_lancar_com_erro_explica_e_nao_deixa_pendencia(bot):
    assert "uso:" in falar(bot, "/lancar 10,00")[0].lower()
    assert "valor" in falar(bot, "/lancar abc 5.02.01 1.01.01 x")[0].lower()
    assert "9.9.9" in falar(bot, "/lancar 10,00 9.9.9 1.01.01 x")[0]
    assert "nada pendente" in falar(bot, "/ok")[0].lower()


def test_nova_proposta_substitui_a_anterior(bot, session):
    falar(bot, "/lancar 10,00 5.02.01 1.01.01 A", update_id=10)
    falar(bot, "/lancar 20,00 5.02.01 1.01.01 B", update_id=11)
    falar(bot, "/ok", update_id=12)
    assert balance(session, "5.02.01") == 2000


# ---- 6.5 idempotência
def test_update_repetido_do_telegram_nao_duplica_nem_responde_de_novo(bot, session):
    falar(bot, "/lancar 45,90 5.02.01 1.01.01 Mercado", update_id=10)
    assert len(falar(bot, "/ok", update_id=11)) == 1
    assert falar(bot, "/ok", update_id=11) == []                      # reenvio do mesmo update
    assert balance(session, "5.02.01") == 4590


def test_idempotencia_sobrevive_a_reinicio_do_bot(bot, session, ctx_factory):
    falar(bot, "/lancar 45,90 5.02.01 1.01.01 Mercado", update_id=10)
    falar(bot, "/ok", update_id=11)
    novo = Bot(ctx_factory, allowed_ids={DONO}, clock=lambda: HOJE)    # memória zerada
    falar(novo, "/lancar 45,90 5.02.01 1.01.01 Mercado", update_id=10)  # Telegram reenviou o /lancar
    falar(novo, "/ok", update_id=11)
    assert balance(session, "5.02.01") == 4590                        # external_ref impediu a duplicata
