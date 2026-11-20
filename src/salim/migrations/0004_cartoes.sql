-- Cartão de crédito: bandeira e final do número (a conta do cartão já tem fechamento e vencimento).
ALTER TABLE accounts ADD COLUMN card_brand TEXT;
ALTER TABLE accounts ADD COLUMN card_last4 TEXT CHECK (card_last4 IS NULL OR length(card_last4) = 4);
