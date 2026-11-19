"""Login de usuário único: senha com scrypt, sessão em cookie assinado, token opcional para scripts."""
import base64
import hashlib
import hmac
import os
import secrets
import time
from dataclasses import dataclass

_N, _R, _P = 16384, 8, 1


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def hash_password(senha: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(senha.encode(), salt=salt, n=_N, r=_R, p=_P)
    return f"scrypt:{_N}:{_R}:{_P}:{_b64(salt)}:{_b64(h)}"


def verify_password(senha: str, guardado: str) -> bool:
    try:
        alg, n, r, p, salt, esperado = guardado.split(":")
        if alg != "scrypt":
            return False
        h = hashlib.scrypt(senha.encode(), salt=_unb64(salt), n=int(n), r=int(r), p=int(p))
        return hmac.compare_digest(h, _unb64(esperado))
    except (ValueError, TypeError):
        return False


@dataclass
class AuthConfig:
    username: str
    password_hash: str
    secret_key: str
    api_token: str | None = None
    cookie_secure: bool = True
    session_days: int = 14

    @classmethod
    def from_env(cls) -> "AuthConfig | None":
        """None só se SALIM_AUTH_DISABLED=1 (dev/teste). Sem senha configurada o app não sobe."""
        senha = os.environ.get("SALIM_PASSWORD_HASH")
        if not senha:
            if os.environ.get("SALIM_AUTH_DISABLED") == "1":
                return None
            raise RuntimeError("defina SALIM_PASSWORD_HASH (gere com `python -m salim.passwd`) "
                               "ou SALIM_AUTH_DISABLED=1 só para desenvolvimento")
        chave = os.environ.get("SALIM_SECRET_KEY", "")
        if not chave:
            raise RuntimeError("defina SALIM_SECRET_KEY (mínimo 32 caracteres aleatórios)")
        if len(chave) < 32:
            raise RuntimeError("SALIM_SECRET_KEY precisa de pelo menos 32 caracteres")
        return cls(username=os.environ.get("SALIM_USER", "admin"), password_hash=senha, secret_key=chave,
                   api_token=os.environ.get("SALIM_API_TOKEN") or None,
                   cookie_secure=os.environ.get("SALIM_COOKIE_SECURE", "1") != "0")


def _sign(cfg: AuthConfig, payload: str) -> str:
    return hmac.new(cfg.secret_key.encode(), payload.encode(), hashlib.sha256).hexdigest()


def make_session(cfg: AuthConfig, now: float | None = None) -> str:
    expira = int((time.time() if now is None else now) + cfg.session_days * 86400)
    payload = _b64(f"{cfg.username}|{expira}".encode())
    return f"{payload}.{_sign(cfg, payload)}"


def read_session(cfg: AuthConfig, cookie: str, now: float | None = None) -> str | None:
    payload, _, assinatura = (cookie or "").rpartition(".")
    if not payload or not hmac.compare_digest(assinatura, _sign(cfg, payload)):
        return None
    try:
        usuario, expira = _unb64(payload).decode().rsplit("|", 1)
    except (ValueError, UnicodeDecodeError):
        return None
    return usuario if (time.time() if now is None else now) < int(expira) else None


class LoginLimiter:
    """Trava global (usuário único): depois de N erros seguidos, recusa tentativas por um tempo."""
    def __init__(self, max_failures: int = 5, lock_seconds: float = 900, clock=time.monotonic):
        self.max, self.lock, self.clock = max_failures, lock_seconds, clock
        self.count, self.until = 0, 0.0

    def locked(self) -> bool:
        if self.clock() < self.until:
            return True
        if self.until:
            self.count, self.until = 0, 0.0
        return False

    def failure(self) -> None:
        self.count += 1
        if self.count >= self.max:
            self.until = self.clock() + self.lock

    def success(self) -> None:
        self.count, self.until = 0, 0.0
