"""Interface preferences of the current user: theme and interface language.

Stored as two columns of the account. Reading needs no database round trip: the
signed-in account is loaded once per request and carries both values.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from masterly.multi_user.context import get_current_user_or_none
from masterly.services.accounts import set_interface

UiTheme = Literal["light", "dark"]
UiLanguage = Literal["vi", "en"]

THEMES: tuple[str, ...] = ("light", "dark")
LANGUAGES: tuple[str, ...] = ("vi", "en")

DEFAULT_UI_SETTINGS: dict[str, Any] = {"theme": "light", "language": "vi"}


def get_ui_settings() -> dict[str, Any]:
    """The signed-in user's theme and language, or the defaults when nobody is."""
    user = get_current_user_or_none()
    if user is None:
        return dict(DEFAULT_UI_SETTINGS)
    return {
        "theme": user.theme if user.theme in THEMES else DEFAULT_UI_SETTINGS["theme"],
        "language": user.language if user.language in LANGUAGES else DEFAULT_UI_SETTINGS["language"],
    }


async def update_ui_settings(
    session: AsyncSession, account_id: uuid.UUID, patch: Mapping[str, Any]
) -> dict[str, Any]:
    """Save the fields in ``patch`` and return the account's resulting settings."""
    updates = {k: v for k, v in patch.items() if k in DEFAULT_UI_SETTINGS}
    await set_interface(session, account_id, **updates)
    await session.commit()
    merged = {**get_ui_settings(), **updates}
    return merged
