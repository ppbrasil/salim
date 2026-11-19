"""Gera o hash de senha para SALIM_PASSWORD_HASH:  python -m salim.passwd"""
import getpass
import secrets
import sys

from salim.auth import hash_password


def main() -> None:
    senha = getpass.getpass("Nova senha (mín. 12 caracteres): ")
    if len(senha) < 12:
        sys.exit("senha curta demais")
    if senha != getpass.getpass("Repita: "):
        sys.exit("as senhas não conferem")
    print(f"SALIM_PASSWORD_HASH={hash_password(senha)}")
    print(f"SALIM_SECRET_KEY={secrets.token_urlsafe(48)}")


if __name__ == "__main__":
    main()
