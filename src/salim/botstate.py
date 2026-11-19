"""Estado dos bots no banco: proposta pendente por chat e updates já processados.

Tudo em SQL portátil (SQLite e Postgres). `pop_pending` é um DELETE ... RETURNING: dois /ok simultâneos
não gravam o mesmo lançamento duas vezes.
"""
import json

from sqlalchemy import text
from sqlalchemy.orm import Session


def put_pending(s: Session, channel: str, chat, proposal: dict, ref: str) -> None:
    s.execute(text("""
        INSERT INTO bot_pending (channel, chat_id, proposal, ref) VALUES (:c, :h, :p, :r)
        ON CONFLICT (channel, chat_id) DO UPDATE SET proposal = excluded.proposal, ref = excluded.ref"""),
              {"c": channel, "h": str(chat), "p": json.dumps(proposal), "r": ref})
    s.commit()


def pop_pending(s: Session, channel: str, chat) -> dict | None:
    row = s.execute(text("DELETE FROM bot_pending WHERE channel = :c AND chat_id = :h RETURNING proposal, ref"),
                    {"c": channel, "h": str(chat)}).first()
    s.commit()
    return None if row is None else {"proposal": json.loads(row[0]), "ref": row[1]}


def first_time(s: Session, channel: str, msg_id, keep: int) -> bool:
    """Marca o update como visto. True na primeira vez; False se já tinha sido visto. Guarda só os `keep` mais recentes."""
    novo = s.execute(text("INSERT INTO bot_seen (channel, msg_id) VALUES (:c, :m) ON CONFLICT DO NOTHING"),
                     {"c": channel, "m": str(msg_id)}).rowcount == 1
    if novo:
        s.execute(text("""
            DELETE FROM bot_seen WHERE channel = :c AND seq <= (
              SELECT seq FROM bot_seen WHERE channel = :c ORDER BY seq DESC LIMIT 1 OFFSET :k)"""),
                  {"c": channel, "k": keep})
    s.commit()
    return novo
