"""Encryption of stored credentials.

Provider API keys in a group's model catalog and its ChatGPT session are
encrypted before they reach the database, with the deployment's
``ENCRYPTION_KEY``. Fernet: AES with an HMAC, so a tampered value fails to
decrypt instead of decrypting to garbage.

Generate a key with::

    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""

from __future__ import annotations

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from masterly.db.config import PROJECT_ROOT

# Marks a stored value as ciphertext, so a value is never decrypted twice and a
# plain value written before encryption existed is still read correctly.
ENCRYPTED_PREFIX = "enc:v1:"


class EncryptionSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", extra="ignore")

    encryption_key: SecretStr = SecretStr("")


class EncryptionKeyError(RuntimeError):
    """``ENCRYPTION_KEY`` is missing, malformed, or not the key the data was written with."""


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    key = EncryptionSettings().encryption_key.get_secret_value()
    if not key:
        raise EncryptionKeyError("ENCRYPTION_KEY is not set; add it to .env (see .env.example)")
    try:
        return Fernet(key)
    except ValueError as exc:
        raise EncryptionKeyError("ENCRYPTION_KEY must be a Fernet key (see .env.example)") from exc


def encrypt_text(value: str) -> str:
    if value.startswith(ENCRYPTED_PREFIX):
        return value
    return ENCRYPTED_PREFIX + _fernet().encrypt(value.encode()).decode()


def decrypt_text(value: str) -> str:
    if not value.startswith(ENCRYPTED_PREFIX):
        return value
    try:
        return _fernet().decrypt(value[len(ENCRYPTED_PREFIX) :].encode()).decode()
    except InvalidToken as exc:
        raise EncryptionKeyError(
            "A stored credential does not decrypt with ENCRYPTION_KEY; was the key changed?"
        ) from exc


def encrypt_bytes(value: bytes) -> bytes:
    return _fernet().encrypt(value)


def decrypt_bytes(value: bytes) -> bytes:
    try:
        return _fernet().decrypt(value)
    except InvalidToken as exc:
        raise EncryptionKeyError(
            "A stored credential does not decrypt with ENCRYPTION_KEY; was the key changed?"
        ) from exc


__all__ = [
    "ENCRYPTED_PREFIX",
    "EncryptionKeyError",
    "decrypt_bytes",
    "decrypt_text",
    "encrypt_bytes",
    "encrypt_text",
]
