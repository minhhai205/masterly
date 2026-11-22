"""
Authentication service for Masterly.

Sign-in is always on. There is no self-registration: the administrator account is
declared in ``data/user/settings/auth.json`` (``username`` plus a bcrypt
``password_hash``) when the system is installed, and every other account is created
by the administrator.

    python -c "from masterly.services.auth import hash_password; print(hash_password('yourpassword'))"

Accounts are stored in ``data/system/`` (see ``masterly.multi_user.identity``).
Sessions are JWT bearer tokens signed with a per-deployment secret and valid for
``token_expire_hours``.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging

from masterly.multi_user.models import AccountPreset, Role
from masterly.services.config import load_auth_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration — read once at import time from runtime JSON settings
# ---------------------------------------------------------------------------

_AUTH_SETTINGS = load_auth_settings()

AUTH_USERNAME: str = str(_AUTH_SETTINGS["username"])
AUTH_PASSWORD_HASH: str = str(_AUTH_SETTINGS["password_hash"])
TOKEN_EXPIRE_HOURS: int = int(_AUTH_SETTINGS["token_expire_hours"])

_ALGORITHM = "HS256"


def _auth_secret() -> str:
    from masterly.multi_user.identity import load_or_create_auth_secret

    return load_or_create_auth_secret()


AUTH_SECRET: str = _auth_secret()


# ---------------------------------------------------------------------------
# Token payload
# ---------------------------------------------------------------------------


@dataclass
class TokenPayload:
    """Decoded JWT payload."""

    username: str
    role: str
    user_id: str = ""


# ---------------------------------------------------------------------------
# Password hashing — bcrypt directly (passlib is unmaintained for bcrypt 4+)
# ---------------------------------------------------------------------------


def hash_password(plain: str) -> str:
    """Hash a plaintext password. Use this to generate password hashes."""
    import bcrypt

    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plaintext password against a stored bcrypt hash."""
    import bcrypt

    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False


# ---------------------------------------------------------------------------
# User store — account store plus the administrator declared in auth.json
# ---------------------------------------------------------------------------


def _load_users() -> dict[str, dict]:
    """Load every account, including the administrator declared in auth.json."""
    from masterly.multi_user.identity import load_users

    return load_users(AUTH_USERNAME, AUTH_PASSWORD_HASH)


def add_user(
    username: str,
    plain_password: str,
    role: Role = "user",
    preset: AccountPreset = "standard",
) -> None:
    """Create or update an account. Accounts other than the administrator are learners."""
    from masterly.multi_user.identity import save_user

    record = save_user(
        username,
        hash_password(plain_password),
        role=role,
        preset=preset,
    )
    logger.info("User '%s' saved with role=%r", username, record.get("role", "user"))


def list_users() -> list[dict]:
    """Return public info dicts (username, role, created_at, …) — no hashes."""
    from masterly.multi_user.identity import list_user_info

    return list_user_info(AUTH_USERNAME, AUTH_PASSWORD_HASH)


def delete_user(username: str) -> bool:
    """Remove an account. Returns True if it existed."""
    from masterly.multi_user.identity import delete_user as _delete_user

    if not _delete_user(username):
        return False
    logger.info("User '%s' deleted", username)
    return True


def set_avatar(username: str, avatar: str) -> bool:
    """
    Update the avatar marker for an existing user. Returns True on success.

    The marker is either '' (deterministic fallback), 'icon:<name>:<color>',
    or 'img:<version>' (managed by the avatar upload endpoint).
    """
    from masterly.multi_user.identity import set_avatar as _set_avatar

    if not _set_avatar(username, avatar):
        return False
    logger.info("User '%s' avatar updated", username)
    return True


def get_user_info(username: str) -> dict | None:
    """Return the public info dict for a single user, or None if unknown."""
    for item in list_users():
        if item.get("username") == username:
            return item
    return None


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------


def create_token(username: str, role: str = "user", user_id: str | None = None) -> str:
    """Create a signed JWT for the given username and role."""
    from jose import jwt

    if not user_id:
        record = _load_users().get(username) or {}
        user_id = str(record.get("id") or "")

    now = datetime.now(timezone.utc)
    payload = {
        "sub": username,
        "role": role,
        "uid": user_id,
        "exp": now + timedelta(hours=TOKEN_EXPIRE_HOURS),
        "iat": now,
    }
    return jwt.encode(payload, AUTH_SECRET, algorithm=_ALGORITHM)


def decode_token(token: str) -> TokenPayload | None:
    """Validate a token and return its payload, or None if invalid or expired."""
    if not token:
        return None

    from jose import JWTError, jwt

    try:
        payload = jwt.decode(token, AUTH_SECRET, algorithms=[_ALGORITHM])
    except JWTError:
        return None
    username = payload.get("sub")
    if not username:
        return None
    user_id = str(payload.get("uid") or "")
    if not user_id:
        record = _load_users().get(str(username)) or {}
        user_id = str(record.get("id") or "")
    return TokenPayload(username=username, role=payload.get("role", "user"), user_id=user_id)


# ---------------------------------------------------------------------------
# Main auth entry point
# ---------------------------------------------------------------------------


def authenticate(username: str, password: str) -> TokenPayload | None:
    """Validate credentials. Returns a TokenPayload on success, None on failure."""
    users = _load_users()
    if not users:
        logger.warning(
            "No accounts configured — login will always fail. "
            "Declare the administrator in data/user/settings/auth.json."
        )
        return None

    record = users.get(username)
    if not isinstance(record, dict) or record.get("disabled"):
        return None
    if not verify_password(password, str(record.get("hash") or "")):
        return None
    return TokenPayload(
        username=username,
        role=str(record.get("role") or "user"),
        user_id=str(record.get("id") or ""),
    )
