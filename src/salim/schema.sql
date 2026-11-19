-- Salim — modelo de dados proposto (SQLite; portável para Postgres)
-- Convenções: dinheiro em centavos (INTEGER); datas em TEXT ISO (YYYY-MM-DD);
-- competência = mês (sempre dia 01); débito > 0, crédito < 0.
PRAGMA foreign_keys = ON;

-- 1. PLANO DE CONTAS -------------------------------------------------------
CREATE TABLE accounts (
  id                  INTEGER PRIMARY KEY,
  code                TEXT NOT NULL UNIQUE,
  name                TEXT NOT NULL,
  type                TEXT NOT NULL CHECK (type IN ('asset','liability','equity','income','expense')),
  parent_id           INTEGER REFERENCES accounts(id),
  is_group            INTEGER NOT NULL DEFAULT 0,
  is_cash             INTEGER NOT NULL DEFAULT 0,  -- banco/carteira: entra no fluxo de caixa
  tracks_obligations  INTEGER NOT NULL DEFAULT 0,  -- toda partida exige um título (obligation)
  is_temporary        INTEGER NOT NULL DEFAULT 0,  -- transição, reembolso, dívida
  closing_day         INTEGER CHECK (closing_day BETWEEN 1 AND 31),  -- só cartão
  due_day             INTEGER CHECK (due_day BETWEEN 1 AND 31),      -- só cartão
  archived            INTEGER NOT NULL DEFAULT 0,
  CHECK (NOT (is_group AND (is_cash OR tracks_obligations)))
);

-- 2. LANÇAMENTOS (imutáveis) -------------------------------------------------
CREATE TABLE transactions (
  id            INTEGER PRIMARY KEY,
  event_date    TEXT NOT NULL,                 -- quando aconteceu (data do caixa, da compra...)
  description   TEXT NOT NULL,
  kind          TEXT NOT NULL DEFAULT 'general',  -- general|purchase|payment|transfer|consolidation|reversal
  reverses_id   INTEGER REFERENCES transactions(id),
  source        TEXT NOT NULL DEFAULT 'web',   -- web|telegram|mcp|openfinance
  external_ref  TEXT UNIQUE,                   -- idempotência (id do extrato, message_id do Telegram)
  created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 3. TÍTULOS: fatura, boleto, parcela, dívida consolidada, reembolso ---------
-- Saldo do título = soma das partidas que apontam para ele. Vencimento mora aqui.
CREATE TABLE obligations (
  id                 INTEGER PRIMARY KEY,
  account_id         INTEGER NOT NULL REFERENCES accounts(id),
  kind               TEXT NOT NULL CHECK (kind IN ('invoice','bill','installment','consolidated','reimbursement','other')),
  reference          TEXT,                     -- '2026-07', 'parc 2/5', 'Copel out/26'
  counterparty       TEXT,                     -- credor/devedor
  due_date           TEXT NOT NULL,            -- vencimento
  closing_date       TEXT,                     -- só fatura: após esta data para de receber compras
  planned_date       TEXT,                     -- data que EU planejo pagar/receber (projeção)
  installment_no     INTEGER,
  installment_total  INTEGER,
  created_by_tx_id   INTEGER NOT NULL REFERENCES transactions(id)  -- agrupa parcelas do mesmo plano
);

-- 4. PARTIDAS (imutáveis) ------------------------------------------------------
CREATE TABLE postings (
  id                INTEGER PRIMARY KEY,
  transaction_id    INTEGER NOT NULL REFERENCES transactions(id),
  account_id        INTEGER NOT NULL REFERENCES accounts(id),
  amount_cents      INTEGER NOT NULL CHECK (amount_cents <> 0),
  competence_month  TEXT NOT NULL CHECK (competence_month = date(competence_month, 'start of month')),
  obligation_id     INTEGER REFERENCES obligations(id),
  memo              TEXT
);
CREATE INDEX ix_postings_tx   ON postings(transaction_id);
CREATE INDEX ix_postings_acc  ON postings(account_id, competence_month);
CREATE INDEX ix_postings_obl  ON postings(obligation_id);

-- 5. ORÇAMENTO (fora do ledger; só leitura sobre ele) -------------------------
CREATE TABLE budget_lines (
  id            INTEGER PRIMARY KEY,
  account_id    INTEGER NOT NULL REFERENCES accounts(id),
  month         TEXT CHECK (month IS NULL OR month = date(month, 'start of month')), -- NULL = mês padrão
  amount_cents  INTEGER NOT NULL CHECK (amount_cents >= 0),
  profile       TEXT NOT NULL DEFAULT 'spread' CHECK (profile IN ('lump','spread')),
  day_of_month  INTEGER CHECK (day_of_month BETWEEN 1 AND 31)  -- quando 'lump'
);
CREATE UNIQUE INDEX ux_budget ON budget_lines(account_id, COALESCE(month, 'default'));

-- INTEGRIDADE NO BANCO ---------------------------------------------------------
CREATE TRIGGER trg_posting_rules BEFORE INSERT ON postings
BEGIN
  SELECT RAISE(ABORT, 'conta-grupo nao recebe lancamento')
    WHERE (SELECT is_group FROM accounts WHERE id = NEW.account_id) = 1;
  SELECT RAISE(ABORT, 'conta exige titulo (obligation_id)')
    WHERE (SELECT tracks_obligations FROM accounts WHERE id = NEW.account_id) = 1
      AND NEW.obligation_id IS NULL;
  SELECT RAISE(ABORT, 'titulo pertence a outra conta')
    WHERE NEW.obligation_id IS NOT NULL
      AND (SELECT account_id FROM obligations WHERE id = NEW.obligation_id) <> NEW.account_id;
END;

CREATE TRIGGER trg_postings_no_update BEFORE UPDATE ON postings
BEGIN SELECT RAISE(ABORT, 'partida imutavel: use estorno'); END;
CREATE TRIGGER trg_postings_no_delete BEFORE DELETE ON postings
BEGIN SELECT RAISE(ABORT, 'partida imutavel: use estorno'); END;
CREATE TRIGGER trg_tx_no_update BEFORE UPDATE ON transactions
BEGIN SELECT RAISE(ABORT, 'lancamento imutavel: use estorno'); END;
CREATE TRIGGER trg_tx_no_delete BEFORE DELETE ON transactions
BEGIN SELECT RAISE(ABORT, 'lancamento imutavel: use estorno'); END;

-- Título: só vencimento, data planejada e referência podem mudar
CREATE TRIGGER trg_obl_frozen_cols BEFORE UPDATE ON obligations
WHEN NEW.account_id <> OLD.account_id OR NEW.created_by_tx_id <> OLD.created_by_tx_id OR NEW.kind <> OLD.kind
BEGIN SELECT RAISE(ABORT, 'titulo: conta, origem e tipo sao imutaveis'); END;
CREATE TRIGGER trg_obl_no_delete BEFORE DELETE ON obligations
BEGIN SELECT RAISE(ABORT, 'titulo nao se apaga'); END;

-- VIEWS ------------------------------------------------------------------------
-- Saldo natural do título (positivo = ainda devo / ainda tenho a receber)
CREATE VIEW v_obligation_balance AS
SELECT o.id AS obligation_id, o.account_id,
       COALESCE(SUM(p.amount_cents), 0)
         * CASE WHEN a.type IN ('asset','expense') THEN 1 ELSE -1 END AS balance_cents
FROM obligations o
JOIN accounts a ON a.id = o.account_id
LEFT JOIN postings p ON p.obligation_id = o.id
GROUP BY o.id;

-- DRE por competência (inclui o que ainda não foi pago)
CREATE VIEW v_dre AS
SELECT p.competence_month AS month, a.code AS account_code, a.type,
       SUM(p.amount_cents * CASE WHEN a.type = 'expense' THEN 1 ELSE -1 END) AS amount_cents
FROM postings p JOIN accounts a ON a.id = p.account_id
WHERE a.type IN ('income','expense')
GROUP BY p.competence_month, a.code;

-- Fluxo de caixa executado (movimento das contas de caixa por data do evento)
CREATE VIEW v_cash_executed AS
SELECT substr(t.event_date, 1, 7) AS month, SUM(p.amount_cents) AS net_cents
FROM postings p
JOIN accounts a ON a.id = p.account_id AND a.is_cash = 1
JOIN transactions t ON t.id = p.transaction_id
GROUP BY substr(t.event_date, 1, 7);

-- Fluxo de caixa futuro: títulos em aberto na data planejada (ou vencimento). Saída < 0.
CREATE VIEW v_cash_future AS
SELECT o.id AS obligation_id, COALESCE(o.planned_date, o.due_date) AS expected_date,
       b.balance_cents * CASE WHEN a.type = 'liability' THEN -1 ELSE 1 END AS expected_cents
FROM obligations o
JOIN v_obligation_balance b ON b.obligation_id = o.id
JOIN accounts a ON a.id = o.account_id
WHERE b.balance_cents > 0;
