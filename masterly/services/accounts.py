"""Accounts, their group and their default learning space, in the database.

Functions take the caller's session and do not commit; the caller decides the
transaction. Emails are compared case-insensitively and stored trimmed.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from masterly.db.models import Account, Group, Workspace
from masterly.services.auth import hash_password, verify_password

DEFAULT_WORKSPACE_NAME = "Mặc định"

# Checked against when an email is unknown, so a wrong email takes as long as a
# wrong password and does not reveal which accounts exist.
_DUMMY_HASH = hash_password("masterly-no-such-account")


def normalize_email(email: str) -> str:
    return email.strip()


async def get_account(session: AsyncSession, account_id: uuid.UUID) -> Account | None:
    return await session.get(Account, account_id)


async def find_account_by_email(session: AsyncSession, email: str) -> Account | None:
    statement = select(Account).where(func.lower(Account.email) == normalize_email(email).lower())
    return await session.scalar(statement)


async def authenticate(session: AsyncSession, email: str, password: str) -> Account | None:
    """The account for these credentials, or None (also for a disabled account)."""
    account = await find_account_by_email(session, email)
    if account is None:
        verify_password(password, _DUMMY_HASH)
        return None
    if not verify_password(password, account.password_hash) or account.disabled:
        return None
    return account


async def create_owner(
    session: AsyncSession, email: str, password: str, display_name: str = ""
) -> Account:
    """Create a group, its owner and the owner's default learning space."""
    group = Group()
    session.add(group)
    await session.flush()
    owner = await _create_account(session, group.id, "owner", email, password, display_name)
    return owner


async def create_learner(
    session: AsyncSession, group_id: uuid.UUID, email: str, password: str, display_name: str = ""
) -> Account:
    """Create a learner in an existing group, with a default learning space."""
    return await _create_account(session, group_id, "learner", email, password, display_name)


async def _create_account(
    session: AsyncSession,
    group_id: uuid.UUID,
    role: str,
    email: str,
    password: str,
    display_name: str,
) -> Account:
    email = normalize_email(email)
    account = Account(
        group_id=group_id,
        role=role,
        email=email,
        password_hash=hash_password(password),
        display_name=display_name.strip() or email.split("@", 1)[0],
    )
    session.add(account)
    await session.flush()
    session.add(Workspace(account_id=account.id, name=DEFAULT_WORKSPACE_NAME, is_default=True))
    await session.flush()
    return account


async def set_avatar(session: AsyncSession, account_id: uuid.UUID, avatar: str) -> None:
    await session.execute(update(Account).where(Account.id == account_id).values(avatar=avatar))


async def set_interface(
    session: AsyncSession,
    account_id: uuid.UUID,
    *,
    theme: str | None = None,
    language: str | None = None,
) -> None:
    values = {k: v for k, v in {"theme": theme, "language": language}.items() if v is not None}
    if values:
        await session.execute(update(Account).where(Account.id == account_id).values(**values))
