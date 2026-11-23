"""Passwords and sessions.

Accounts live in the ``accounts`` table (see ``masterly.services.accounts``). A
session is a JWT carrying only the account id, signed with ``AUTH_SECRET`` and
valid for ``SESSION_TTL_HOURS``; every request reads the account again, so a
disabled or deleted account loses access at once.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import lru_cache
import uuid

import bcrypt
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from masterly.db.config import PROJECT_ROOT

_ALGORITHM = "HS256"


class AuthSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", extra="ignore")

    auth_secret: SecretStr = SecretStr("")
    session_ttl_hours: int = 24
    cookie_secure: bool = False


@lru_cache(maxsize=1)
def get_auth_settings() -> AuthSettings:
    return AuthSettings()


def _secret() -> str:
    secret = get_auth_settings().auth_secret.get_secret_value()
    if not secret:
        raise RuntimeError("AUTH_SECRET is not set; add it to .env (see .env.example)")
    return secret


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except ValueError:
        return False


def create_token(account_id: uuid.UUID) -> str:
    from jose import jwt

    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(account_id),
        "iat": now,
        "exp": now + timedelta(hours=get_auth_settings().session_ttl_hours),
    }
    return jwt.encode(payload, _secret(), algorithm=_ALGORITHM)


def decode_token(token: str | None) -> uuid.UUID | None:
    """The account id of a valid, unexpired session token, or None."""
    if not token:
        return None
    from jose import JWTError, jwt

    try:
        payload = jwt.decode(token, _secret(), algorithms=[_ALGORITHM])
        return uuid.UUID(str(payload.get("sub")))
    except (JWTError, ValueError):
        return None
