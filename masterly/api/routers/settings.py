"""Interface preferences: theme (light/dark) and interface language (vi/en).

``GET /ui`` is public on purpose: the sign-in page needs the theme and language
before anyone is signed in, and then gets the defaults. With a session it returns
that account's own preferences. Saving requires a session.
"""

from typing import Literal
import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from masterly.api.routers.auth import optional_auth, require_auth
from masterly.db import get_session
from masterly.multi_user.models import CurrentUser
from masterly.services.settings.interface_settings import get_ui_settings, update_ui_settings

public_router = APIRouter()
router = APIRouter()


class UISettingsUpdate(BaseModel):
    """Partial update: only the fields sent are saved."""

    theme: Literal["light", "dark"] | None = None
    language: Literal["vi", "en"] | None = None


@public_router.get("/ui", dependencies=[Depends(optional_auth)])
async def read_ui_settings() -> dict:
    return get_ui_settings()


@router.put("/ui")
async def save_ui_settings(
    update: UISettingsUpdate,
    current: CurrentUser = Depends(require_auth),
    session: AsyncSession = Depends(get_session),
) -> dict:
    patch = update.model_dump(exclude_unset=True, exclude_none=True)
    return await update_ui_settings(session, uuid.UUID(current.id), patch)
