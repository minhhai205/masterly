"""Sign-in, session and own-profile endpoints, plus the auth guards other routers use.

Sign-in is always on. Sessions are JWTs carried in an httpOnly cookie (or an
``Authorization: Bearer`` header). There is no self-registration; account
management for the administrator arrives with F02.
"""

from contextvars import Token as _CtxToken
import logging
import re

from fastapi import (
    APIRouter,
    Cookie,
    Depends,
    File,
    Header,
    HTTPException,
    Response,
    UploadFile,
    WebSocket,
    status,
)
from fastapi.responses import FileResponse
from pydantic import BaseModel, field_validator

from masterly.multi_user.context import (
    reset_current_user,
    set_current_user,
    user_from_token_payload,
)
from masterly.services.auth import (
    TOKEN_EXPIRE_HOURS,
    TokenPayload,
    authenticate,
    create_token,
    decode_token,
    get_user_info,
    set_avatar,
)
from masterly.services.config import load_auth_settings

logger = logging.getLogger(__name__)

router = APIRouter()

COOKIE_NAME = "masterly_token"
_COOKIE_MAX_AGE = TOKEN_EXPIRE_HOURS * 3600
_SECURE = bool(load_auth_settings()["cookie_secure"])
_SAMESITE = "none" if _SECURE else "lax"


def _cookie_attrs() -> dict:
    """Attributes shared by login's ``set_cookie`` and logout's ``delete_cookie``.

    The deleting ``Set-Cookie`` must carry the same attributes as the one that
    created the cookie, or browsers keep the old cookie.
    """
    return {"key": COOKIE_NAME, "httponly": True, "samesite": _SAMESITE, "secure": _SECURE}


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    username: str
    password: str


class AuthStatusResponse(BaseModel):
    authenticated: bool
    user_id: str | None = None
    username: str | None = None
    role: str | None = None
    is_admin: bool = False
    avatar: str = ""


class UserInfo(BaseModel):
    id: str = ""
    username: str
    role: str
    created_at: str
    disabled: bool = False
    avatar: str = ""


# Markers settable through PUT /profile. Image markers ("img:<version>") are
# managed only by the upload endpoint, so an avatar can never point at a file
# that was not validated.
_ICON_MARKER_RE = re.compile(r"^icon:[a-z0-9-]{1,32}:[a-z0-9-]{1,32}$")

# User ids are generated as "u_<uuid hex>" (plus the "env-admin" sentinel);
# anything else is rejected before it reaches the filesystem.
_USER_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class UpdateProfileRequest(BaseModel):
    avatar: str

    @field_validator("avatar")
    @classmethod
    def avatar_valid(cls, v: str) -> str:
        v = v.strip()
        if v and not _ICON_MARKER_RE.match(v):
            raise ValueError("Avatar must be empty or 'icon:<name>:<color>'")
        return v


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


def _install_current_user(payload: TokenPayload) -> _CtxToken:
    """Install the request-local current user. Every authenticated entry point must
    call this before the handler runs, or data paths would resolve to the wrong
    account."""
    return set_current_user(user_from_token_payload(payload))


async def require_auth(
    authorization: str | None = Header(default=None, alias="Authorization"),
    cookie_token: str | None = Cookie(default=None, alias=COOKIE_NAME),
) -> TokenPayload:
    """Require a valid session and install the current user.

    ``async def`` on purpose: a sync dependency runs in a worker thread under a
    copy of the request context, and the current-user ContextVar set there would
    be lost before the endpoint runs.

    Learning-space scoping: phase 1 has the default learning space only, so no
    per-request workspace is installed and data resolves to the account's default
    space.
    """
    token = _extract_token(authorization, cookie_token)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = decode_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    _install_current_user(payload)
    return payload


async def require_admin(payload: TokenPayload = Depends(require_auth)) -> TokenPayload:
    """Require the administrator."""
    if payload.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return payload


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
    payload = decode_token(token) if token else None
    if not payload:
        await ws.close(code=4001)
        return ws_auth_failed
    return _install_current_user(payload)


__all__ = [
    "COOKIE_NAME",
    "require_admin",
    "require_auth",
    "reset_current_user",
    "router",
    "ws_auth_failed",
    "ws_require_auth",
]


# ---------------------------------------------------------------------------
# Session endpoints (public)
# ---------------------------------------------------------------------------


@router.get("/status", response_model=AuthStatusResponse)
async def auth_status(
    authorization: str | None = Header(default=None, alias="Authorization"),
    cookie_token: str | None = Cookie(default=None, alias=COOKIE_NAME),
) -> AuthStatusResponse:
    """Whether the current request carries a valid session, and who it belongs to."""
    token = _extract_token(authorization, cookie_token)
    payload = decode_token(token) if token else None
    if payload is None:
        return AuthStatusResponse(authenticated=False)
    info = get_user_info(payload.username) or {}
    return AuthStatusResponse(
        authenticated=True,
        user_id=payload.user_id,
        username=payload.username,
        role=payload.role,
        is_admin=payload.role == "admin",
        avatar=str(info.get("avatar") or ""),
    )


@router.post("/login")
async def login(body: LoginRequest, response: Response) -> dict:
    """Check the credentials and set the session cookie."""
    _no_store(response)
    result = authenticate(body.username, body.password)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )
    token = create_token(result.username, result.role, result.user_id)
    response.set_cookie(value=token, max_age=_COOKIE_MAX_AGE, **_cookie_attrs())
    logger.info("User '%s' logged in (role=%r)", result.username, result.role)
    return {
        "ok": True,
        "user_id": result.user_id,
        "username": result.username,
        "role": result.role,
        "is_admin": result.role == "admin",
    }


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
async def get_profile(current: TokenPayload = Depends(require_auth)) -> UserInfo:
    """The current user's own account info."""
    info = get_user_info(current.username)
    if info is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return UserInfo(**{k: v for k, v in info.items() if k in UserInfo.model_fields})


@router.put("/profile")
async def update_profile(
    body: UpdateProfileRequest,
    current: TokenPayload = Depends(require_auth),
) -> dict:
    """Pick an icon avatar (``icon:<name>:<color>``) or reset to the default."""
    if not set_avatar(current.username, body.avatar):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    # The marker no longer points at an uploaded image, so drop the file.
    from masterly.multi_user.identity import delete_avatar_file

    if current.user_id and _USER_ID_RE.match(current.user_id):
        delete_avatar_file(current.user_id)
    return {"ok": True, "avatar": body.avatar}


@router.put("/profile/avatar")
async def upload_avatar(
    file: UploadFile = File(...),
    current: TokenPayload = Depends(require_auth),
) -> dict:
    """Upload an avatar image. The client crops it; the server caps the size and
    checks the format from the bytes."""
    if not current.user_id or not _USER_ID_RE.match(current.user_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot store an avatar for this account.",
        )
    info = get_user_info(current.username)
    if info is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

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

    from masterly.multi_user.identity import save_avatar_file

    # Bump the version in the marker so clients refetch the image.
    previous = str(info.get("avatar") or "")
    version = 1
    if previous.startswith("img:"):
        try:
            version = int(previous.split(":", 1)[1]) + 1
        except ValueError:
            version = 1
    marker = f"img:{version}"

    save_avatar_file(current.user_id, data, ext)
    if not set_avatar(current.username, marker):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    logger.info("User '%s' uploaded a new avatar (%s, %d bytes)", current.username, ext, len(data))
    return {"ok": True, "avatar": marker}


@router.delete("/profile/avatar")
async def remove_avatar(current: TokenPayload = Depends(require_auth)) -> dict:
    """Remove the uploaded avatar image and reset the marker."""
    from masterly.multi_user.identity import delete_avatar_file

    if current.user_id and _USER_ID_RE.match(current.user_id):
        delete_avatar_file(current.user_id)
    set_avatar(current.username, "")
    return {"ok": True, "avatar": ""}


@router.get("/avatar/{user_id}")
async def get_avatar_image(
    user_id: str,
    _: TokenPayload = Depends(require_auth),
) -> FileResponse:
    """Serve a stored avatar image to any signed-in user."""
    if not _USER_ID_RE.match(user_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Avatar not found")

    from masterly.multi_user.identity import get_avatar_file

    target = get_avatar_file(user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Avatar not found")

    media_type = _AVATAR_MEDIA_TYPES.get(target.suffix.lstrip("."), "application/octet-stream")
    headers = {
        "Cache-Control": "private, max-age=86400",
        "X-Content-Type-Options": "nosniff",
        "Content-Disposition": "inline",
    }
    return FileResponse(path=str(target), media_type=media_type, headers=headers)
