"""Sign-in, session and own-profile endpoints, plus the auth guards other routers use.

Anyone may register: registering creates a group and its owner. Sessions are
JWTs carried in an httpOnly cookie (or an ``Authorization: Bearer`` header) that
name an account. Every guarded request loads that account from the
database and installs it as the current user; a disabled or deleted account is
treated as signed out.
"""

from __future__ import annotations

from contextvars import Token as _CtxToken
import logging
import re
import uuid

from fastapi import (
    APIRouter,
    Cookie,
    Depends,
    File,
    Header,
    HTTPException,
    Request,
    Response,
    UploadFile,
    WebSocket,
    status,
)
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from masterly.db import get_session, get_session_factory
from masterly.db.models import Account
from masterly.multi_user.context import current_user_for, reset_current_user, set_current_user
from masterly.multi_user.models import CurrentUser
from masterly.services import accounts
from masterly.services.auth import create_token, decode_token, get_auth_settings
from masterly.services.codex_auth.contracts import CodexAuthError
from masterly.services.codex_auth.service import deliver_codex_oauth_callback
from masterly.services.config.group_catalog import refresh_group_catalog
from masterly.storage import get_storage

logger = logging.getLogger(__name__)

router = APIRouter()

COOKIE_NAME = "masterly_token"


def _cookie_attrs() -> dict:
    """Attributes shared by login's ``set_cookie`` and logout's ``delete_cookie``.

    The deleting ``Set-Cookie`` must carry the same attributes as the one that
    created the cookie, or browsers keep the old cookie.
    """
    secure = get_auth_settings().cookie_secure
    return {
        "key": COOKIE_NAME,
        "httponly": True,
        "samesite": "none" if secure else "lax",
        "secure": secure,
    }


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    email: str
    password: str


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    display_name: str = Field(default="", max_length=80)

    @field_validator("password")
    @classmethod
    def password_fits_bcrypt(cls, v: str) -> str:
        # bcrypt reads at most 72 bytes; refuse rather than silently truncate.
        if len(v.encode()) > 72:
            raise ValueError("Password must be at most 72 bytes")
        return v


class AuthStatusResponse(BaseModel):
    authenticated: bool
    user_id: str | None = None
    email: str | None = None
    display_name: str | None = None
    role: str | None = None
    is_owner: bool = False
    avatar: str = ""


class UserInfo(BaseModel):
    id: str
    email: str
    display_name: str
    role: str
    created_at: str
    avatar: str = ""


# Markers settable through PUT /profile. Image markers ("img:<version>") are
# managed only by the upload endpoint, so an avatar can never point at a file
# that was not validated.
_ICON_MARKER_RE = re.compile(r"^icon:[a-z0-9-]{1,32}:[a-z0-9-]{1,32}$")


class UpdateProfileRequest(BaseModel):
    avatar: str

    @field_validator("avatar")
    @classmethod
    def avatar_valid(cls, v: str) -> str:
        v = v.strip()
        if v and not _ICON_MARKER_RE.match(v):
            raise ValueError("Avatar must be empty or 'icon:<name>:<color>'")
        return v


def _user_info(user: CurrentUser) -> UserInfo:
    return UserInfo(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=user.role,
        created_at=user.created_at,
        avatar=user.avatar,
    )


# ---------------------------------------------------------------------------
# Token extraction and guards for other routers
# ---------------------------------------------------------------------------


def _bearer_token_from_header(authorization: str | None) -> str | None:
    """Parse ``Authorization: Bearer <token>`` by hand so the guard also works for
    WebSocket call sites (``HTTPBearer`` needs a Request)."""
    if not authorization:
        return None
    parts = authorization.split(None, 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip() or None
    return None


def _extract_token(authorization: str | None, cookie_token: str | None) -> str | None:
    return _bearer_token_from_header(authorization) or cookie_token


async def _signed_in_user(token: str | None) -> CurrentUser | None:
    """The account a session token names, if it still exists and is enabled."""
    account_id = decode_token(token)
    if account_id is None:
        return None
    async with get_session_factory()() as session:
        account = await accounts.get_account(session, account_id)
        if account is None or account.disabled:
            return None
        # Every request of a group runs on that group's catalog; pick up a
        # change saved by another process before anything resolves a model.
        await refresh_group_catalog(session, str(account.group_id))
    return current_user_for(account)


async def require_auth(
    authorization: str | None = Header(default=None, alias="Authorization"),
    cookie_token: str | None = Cookie(default=None, alias=COOKIE_NAME),
) -> CurrentUser:
    """Require a valid session and install the current user.

    ``async def`` on purpose: a sync dependency runs in a worker thread under a
    copy of the request context, and the current-user ContextVar set there would
    be lost before the endpoint runs.
    """
    user = await _signed_in_user(_extract_token(authorization, cookie_token))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    set_current_user(user)
    return user


async def optional_auth(
    authorization: str | None = Header(default=None, alias="Authorization"),
    cookie_token: str | None = Cookie(default=None, alias=COOKIE_NAME),
) -> CurrentUser | None:
    """Install the current user when a valid session is present; otherwise carry on
    anonymously. For public endpoints whose answer depends on who is asking."""
    user = await _signed_in_user(_extract_token(authorization, cookie_token))
    if user is not None:
        set_current_user(user)
    return user


async def require_owner(user: CurrentUser = Depends(require_auth)) -> CurrentUser:
    """Require the owner of the group."""
    if not user.is_owner:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Group owner only")
    return user


class _WsAuthFailed:
    """Sentinel: ws_require_auth failed and closed the WebSocket."""


ws_auth_failed: _WsAuthFailed = _WsAuthFailed()


async def ws_require_auth(ws: WebSocket) -> _CtxToken | _WsAuthFailed:
    """Authenticate a WebSocket before ``accept`` and install the current user.

    Returns a ContextVar reset token, or ``ws_auth_failed`` when the socket was
    closed. The caller resets the user in its ``finally`` block, because the
    connection outlives the dependency-resolution task.
    """
    token = ws.query_params.get("token") or ws.cookies.get(COOKIE_NAME)
    user = await _signed_in_user(token)
    if user is None:
        await ws.close(code=4001)
        return ws_auth_failed
    return set_current_user(user)


__all__ = [
    "COOKIE_NAME",
    "optional_auth",
    "require_auth",
    "require_owner",
    "reset_current_user",
    "router",
    "ws_auth_failed",
    "ws_require_auth",
]


# ---------------------------------------------------------------------------
# Session endpoints (public)
# ---------------------------------------------------------------------------


@router.get("/openai-codex/callback")
async def receive_codex_oauth_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> HTMLResponse:
    """Hand a ChatGPT sign-in redirect to the login waiting for it.

    Public on purpose: the browser arrives from the provider without a session.
    The one-time OAuth ``state`` identifies the login instead.
    """
    headers = {"Cache-Control": "no-store"}
    try:
        callback_state = state if len(request.query_params.getlist("state")) == 1 else None
        await deliver_codex_oauth_callback(code, callback_state, error)
    except CodexAuthError as exc:
        return HTMLResponse(
            (
                "<!doctype html><title>Masterly Codex</title>"
                "<p>Authentication could not be received. Return to Masterly and try again.</p>"
            ),
            status_code=exc.http_status,
            headers=headers,
        )
    return HTMLResponse(
        (
            "<!doctype html><title>Masterly Codex</title>"
            "<p>Authentication received. You can return to Masterly.</p>"
        ),
        headers=headers,
    )


@router.get("/status", response_model=AuthStatusResponse)
async def auth_status(
    authorization: str | None = Header(default=None, alias="Authorization"),
    cookie_token: str | None = Cookie(default=None, alias=COOKIE_NAME),
) -> AuthStatusResponse:
    """Whether the current request carries a valid session, and who it belongs to."""
    user = await _signed_in_user(_extract_token(authorization, cookie_token))
    if user is None:
        return AuthStatusResponse(authenticated=False)
    return AuthStatusResponse(
        authenticated=True,
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=user.role,
        is_owner=user.is_owner,
        avatar=user.avatar,
    )


def _start_session(response: Response, account: Account) -> dict:
    response.set_cookie(
        value=create_token(account.id),
        max_age=get_auth_settings().session_ttl_hours * 3600,
        **_cookie_attrs(),
    )
    return {
        "ok": True,
        "user_id": str(account.id),
        "email": account.email,
        "role": account.role,
        "is_owner": account.role == "owner",
    }


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    body: RegisterRequest,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Create a group with its owner, and sign the new owner in."""
    _no_store(response)
    taken = HTTPException(
        status_code=status.HTTP_409_CONFLICT, detail="An account with this email already exists"
    )
    if await accounts.find_account_by_email(session, body.email) is not None:
        raise taken
    try:
        account = await accounts.create_owner(
            session, body.email, body.password, body.display_name
        )
        await session.commit()
    except IntegrityError:
        # Another registration took the email between the check and the insert.
        await session.rollback()
        raise taken from None
    logger.info("Account %s registered a new group %s", account.id, account.group_id)
    return _start_session(response, account)


@router.post("/login")
async def login(
    body: LoginRequest,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Check the credentials and set the session cookie."""
    _no_store(response)
    account = await accounts.authenticate(session, body.email, body.password)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )
    logger.info("Account %s signed in (role=%s)", account.id, account.role)
    return _start_session(response, account)


@router.post("/logout")
async def logout(response: Response) -> dict:
    """Clear the session cookie."""
    response.delete_cookie(**_cookie_attrs())
    return {"ok": True}


# ---------------------------------------------------------------------------
# Own profile
# ---------------------------------------------------------------------------

_AVATAR_MAX_BYTES = 1 * 1024 * 1024
_AVATAR_MEDIA_TYPES = {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp"}


def _avatar_key(group_id: str, account_id: str) -> str:
    """Storage key of an account's avatar; one object, replaced on each upload."""
    return f"{group_id}/{account_id}/avatar"


def _sniff_image(data: bytes) -> str | None:
    """Detect PNG, JPEG or WebP from the bytes. The filename and Content-Type come
    from the client and are not trusted; SVG is refused (stored XSS)."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


@router.get("/profile", response_model=UserInfo)
async def get_profile(current: CurrentUser = Depends(require_auth)) -> UserInfo:
    """The current user's own account info."""
    return _user_info(current)


@router.put("/profile")
async def update_profile(
    body: UpdateProfileRequest,
    current: CurrentUser = Depends(require_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Pick an icon avatar (``icon:<name>:<color>``) or reset to the default."""
    await accounts.set_avatar(session, uuid.UUID(current.id), body.avatar)
    await session.commit()
    await get_storage().delete(_avatar_key(current.group_id, current.id))
    return {"ok": True, "avatar": body.avatar}


@router.put("/profile/avatar")
async def upload_avatar(
    file: UploadFile = File(...),
    current: CurrentUser = Depends(require_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Upload an avatar image. The client crops it; the server caps the size and
    checks the format from the bytes."""
    data = await file.read(_AVATAR_MAX_BYTES + 1)
    if len(data) > _AVATAR_MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Avatar image is too large (max 1 MB).",
        )
    ext = _sniff_image(data)
    if ext is None:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Avatar must be a PNG, JPEG or WebP image.",
        )

    # Bump the version in the marker so clients refetch the image.
    version = 1
    if current.avatar.startswith("img:"):
        try:
            version = int(current.avatar.split(":", 1)[1]) + 1
        except ValueError:
            version = 1
    marker = f"img:{version}"

    await get_storage().put(_avatar_key(current.group_id, current.id), data, _AVATAR_MEDIA_TYPES[ext])
    await accounts.set_avatar(session, uuid.UUID(current.id), marker)
    await session.commit()
    logger.info("Account %s uploaded a new avatar (%s, %d bytes)", current.id, ext, len(data))
    return {"ok": True, "avatar": marker}


@router.delete("/profile/avatar")
async def remove_avatar(
    current: CurrentUser = Depends(require_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Remove the uploaded avatar image and reset the marker."""
    await get_storage().delete(_avatar_key(current.group_id, current.id))
    await accounts.set_avatar(session, uuid.UUID(current.id), "")
    await session.commit()
    return {"ok": True, "avatar": ""}


@router.get("/avatar/{user_id}")
async def get_avatar_image(
    user_id: str,
    current: CurrentUser = Depends(require_auth),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Serve the avatar image of an account in the caller's own group."""
    try:
        account = await accounts.get_account(session, uuid.UUID(user_id))
    except ValueError:
        account = None
    if account is None or str(account.group_id) != current.group_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Avatar not found")

    data = await get_storage().get(_avatar_key(str(account.group_id), str(account.id)))
    ext = _sniff_image(data) if data else None
    if ext is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Avatar not found")

    headers = {
        "Cache-Control": "private, max-age=86400",
        "X-Content-Type-Options": "nosniff",
        "Content-Disposition": "inline",
    }
    return Response(content=data, media_type=_AVATAR_MEDIA_TYPES[ext], headers=headers)
