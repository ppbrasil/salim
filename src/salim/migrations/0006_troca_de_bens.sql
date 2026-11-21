-- Troca de um bem: o que vai trocar, quanto custa um novo hoje e por quanto venderia o usado (meta com perda = novo - usado).
ALTER TABLE reserves ADD COLUMN category TEXT;
ALTER TABLE reserves ADD COLUMN new_price_cents BIGINT CHECK (new_price_cents IS NULL OR new_price_cents > 0);
ALTER TABLE reserves ADD COLUMN resale_cents BIGINT CHECK (resale_cents IS NULL OR resale_cents >= 0);
