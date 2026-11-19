"""M4: o estado do bot (proposta pendente, updates já vistos) vive no banco, não na memória do processo."""
from datetime import date

import pytest
from sqlalchemy import text

from salim.chart import seed_chart
from salim.channels import WhatsAppChannel
from salim.ledger import balance
from salim.telegram import Bot

DONO = 111
HOJE = date(2026, 8, 12)


def msg(texto, update_id, chat=DONO):
    return {"update_id": update_id, "message": {"message_id": update_id, "chat": {"id": chat},
                                                 "from": {"id": chat}, "text": texto}}


def fala(bot, texto, update_id, chat=DONO):
    return [r.text for r in bot.handle(msg(texto, update_id, chat))]


def novo_bot(ctx_factory, **kw):
    return Bot(ctx_factory, allowed_ids={DONO, 222}, clock=lambda: HOJE, **kw)


@pytest.fixture
def base(session, ctx_factory):
    seed_chart(session)
    return ctx_factory


def test_proposta_pendente_sobrevive_a_novo_processo(base, session):
    fala(novo_bot(base), "/lancar 10,00 5.02.01 1.01.01 Padaria", 1)
    outro_processo = novo_bot(base)                       # instância nova, sem memória
    assert fala(outro_processo, "/ok", 2)[0].startswith("Registrado")
    assert balance(session, "5.02.01") == 1000


def test_ok_consome_a_proposta_uma_so_vez(base, session):
    b = novo_bot(base)
    fala(b, "/lancar 10,00 5.02.01 1.01.01 Padaria", 1)
    assert fala(novo_bot(base), "/ok", 2)[0].startswith("Registrado")
    assert fala(novo_bot(base), "/ok", 3) == ["Nada pendente."]
    assert balance(session, "5.02.01") == 1000


def test_cancelar_apaga_do_banco(base):
    fala(novo_bot(base), "/lancar 10,00 5.02.01 1.01.01 Padaria", 1)
    assert fala(novo_bot(base), "/cancelar", 2) == ["Proposta cancelada."]
    assert fala(novo_bot(base), "/ok", 3) == ["Nada pendente."]


def test_nova_proposta_substitui_a_anterior_no_mesmo_chat(base, session):
    fala(novo_bot(base), "/lancar 10,00 5.02.01 1.01.01 A", 1)
    fala(novo_bot(base), "/lancar 20,00 5.02.01 1.01.01 B", 2)
    fala(novo_bot(base), "/ok", 3)
    assert balance(session, "5.02.01") == 2000
    with base() as s:
        assert s.execute(text("select count(*) from bot_pending")).scalar_one() == 0


def test_chats_diferentes_nao_se_misturam(base, session):
    fala(novo_bot(base), "/lancar 10,00 5.02.01 1.01.01 Do dono", 1, chat=DONO)
    assert fala(novo_bot(base), "/ok", 2, chat=222) == ["Nada pendente."]
    assert fala(novo_bot(base), "/ok", 3, chat=DONO)[0].startswith("Registrado")


def test_canais_diferentes_com_mesmo_id_nao_se_misturam(base):
    tg = novo_bot(base)
    wa = Bot(base, allowed_ids={"111"}, clock=lambda: HOJE, channel=WhatsAppChannel())
    fala(tg, "/lancar 10,00 5.02.01 1.01.01 Padaria", 1)
    with base() as s:
        canais = s.execute(text("select channel from bot_pending")).scalars().all()
    assert canais == ["telegram"]
    assert wa._cancelar("111", None, "") == "Nada pendente."


def test_update_repetido_e_ignorado_mesmo_por_outro_processo(base):
    assert fala(novo_bot(base), "/saldo", 7) != []
    assert fala(novo_bot(base), "/saldo", 7) == []


def test_memoria_de_updates_e_limitada_e_esquece_o_mais_antigo(base):
    b = novo_bot(base, remember_updates=3)
    for uid in (1, 2, 3, 4):
        fala(b, "/saldo", uid)
    with base() as s:
        assert s.execute(text("select count(*) from bot_seen")).scalar_one() == 3
    assert fala(novo_bot(base, remember_updates=3), "/saldo", 4) == []      # recente: ainda lembra
    assert fala(novo_bot(base, remember_updates=3), "/saldo", 1) != []      # o mais antigo foi esquecido
