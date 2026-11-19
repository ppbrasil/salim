-- Estado dos bots de mensagem (Telegram/WhatsApp) no banco: o processo serverless não guarda memória entre chamadas.
CREATE TABLE bot_pending (
  channel    TEXT NOT NULL,
  chat_id    TEXT NOT NULL,
  proposal   TEXT NOT NULL,                  -- JSON da proposta mostrada ao usuário
  ref        TEXT NOT NULL,                  -- external_ref que o /ok vai gravar (idempotência)
  created_at TIMESTAMP NOT NULL DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC'),
  PRIMARY KEY (channel, chat_id)
);

CREATE TABLE bot_seen (
  seq     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  channel TEXT NOT NULL,
  msg_id  TEXT NOT NULL,
  UNIQUE (channel, msg_id)
);
