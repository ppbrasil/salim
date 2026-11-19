-- Trava de tentativas de login (usuário único: uma linha global). Só contagem e prazo; nada de senha nem IP.
CREATE TABLE login_throttle (
  key          TEXT PRIMARY KEY,
  failures     INTEGER NOT NULL DEFAULT 0,
  locked_until DOUBLE PRECISION NOT NULL DEFAULT 0     -- segundos desde 1970 (UTC)
);
