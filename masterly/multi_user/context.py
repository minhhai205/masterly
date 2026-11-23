"""Request-local current user context."""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import TYPE_CHECKING

from .models import CurrentUser
from .paths import local_admin_user, scope_for_user

if TYPE_CHECKING:
    from masterly.db.models import Account

_current_user: ContextVar[CurrentUser | None] = ContextVar("masterly_current_user", default=None)


def set_current_user(user: CurrentUser) -> Token[CurrentUser | None]:
    return _current_user.set(user)


def reset_current_user(token: Token[CurrentUser | None]) -> None:
    _current_user.reset(token)


def get_current_user() -> CurrentUser:
    """The signed-in account, or the deployment itself outside a request."""
    return _current_user.get() or local_admin_user()


def get_current_user_or_none() -> CurrentUser | None:
    return _current_user.get()


def current_user_for(account: Account) -> CurrentUser:
    account_id = str(account.id)
    return CurrentUser(
        id=account_id,
        email=account.email,
        display_name=account.display_name,
        role=account.role,  # type: ignore[arg-type]
        group_id=str(account.group_id),
        scope=scope_for_user(account_id),
        avatar=account.avatar,
        theme=account.theme,
        language=account.language,
        created_at=account.created_at.isoformat() if account.created_at else "",
    )
