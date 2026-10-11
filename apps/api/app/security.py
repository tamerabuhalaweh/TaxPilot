"""Password, token, and identifier helpers. Secrets never leave this module raw."""

import hashlib
import secrets

import bcrypt
from email_validator import EmailNotValidError, validate_email

BCRYPT_ROUNDS = 12


def normalize_email(raw: str) -> str:
    try:
        return validate_email(raw.strip(), check_deliverability=False).normalized.lower()
    except EmailNotValidError as exc:
        raise ValueError(f"invalid email: {exc}") from exc


def validate_password(password: str, minimum: int = 12) -> None:
    if len(password) < minimum:
        raise ValueError(f"password must be at least {minimum} characters")
    if len(password) > 128:
        raise ValueError("password must be at most 128 characters")


def hash_password(password: str) -> str:
    # SHA-256 pre-hash: bcrypt truncates past 72 bytes; the digest keeps long
    # passphrases fully effective while the stored value stays bcrypt-hashed.
    digest = hashlib.sha256(password.encode("utf-8")).digest()
    return bcrypt.hashpw(digest, bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode()


def verify_password(password: str, stored: str) -> bool:
    try:
        digest = hashlib.sha256(password.encode("utf-8")).digest()
        return bcrypt.checkpw(digest, stored.encode())
    except Exception:
        return False


def new_token(bytes_: int = 32) -> str:
    return secrets.token_urlsafe(bytes_)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
