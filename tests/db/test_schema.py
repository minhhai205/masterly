"""The initial migration builds the designed schema and the models match it."""

from __future__ import annotations

import asyncio
import uuid

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
import pytest
import pytest_asyncio
from sqlalchemy import delete, insert, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from masterly.db.models import Account, Base, Group, LearningPath, Session, Workspace

TABLES = {
    "groups",
    "accounts",
    "workspaces",
    "memories",
    "sessions",
    "messages",
    "turns",
    "turn_events",
    "learning_paths",
    "assessments",
    "knowledge_bases",
    "documents",
    "chunks",
    "notes",
}


@pytest_asyncio.fixture
async def engine(database_url):
    engine = create_async_engine(database_url)
    yield engine
    await engine.dispose()


async def _tables(engine) -> set[str]:
    async with engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
        )
        return {row[0] for row in rows} - {"alembic_version"}


@pytest.mark.asyncio
async def test_migration_creates_every_designed_table(engine):
    assert await _tables(engine) == TABLES


@pytest.mark.asyncio
async def test_models_match_the_migrated_schema(engine):
    def diff(sync_conn):
        return compare_metadata(MigrationContext.configure(sync_conn), Base.metadata)

    async with engine.connect() as conn:
        assert await conn.run_sync(diff) == []


async def _new_group_with_owner(conn, email: str) -> tuple[uuid.UUID, uuid.UUID]:
    group_id, owner_id = uuid.uuid4(), uuid.uuid4()
    await conn.execute(insert(Group).values(id=group_id))
    await conn.execute(
        insert(Account).values(
            id=owner_id, group_id=group_id, role="owner", email=email, password_hash="x"
        )
    )
    return group_id, owner_id


@pytest.mark.asyncio
async def test_email_is_unique_regardless_of_case(engine):
    async with engine.connect() as conn:
        await _new_group_with_owner(conn, "Owner@Example.com")
        with pytest.raises(IntegrityError):
            await _new_group_with_owner(conn, "owner@example.com")
        await conn.rollback()


@pytest.mark.asyncio
async def test_a_group_has_exactly_one_owner(engine):
    async with engine.connect() as conn:
        group_id, _ = await _new_group_with_owner(conn, f"{uuid.uuid4().hex}@example.com")
        await conn.execute(
            insert(Account).values(
                group_id=group_id, role="learner", email=f"{uuid.uuid4().hex}@x.com", password_hash="x"
            )
        )
        with pytest.raises(IntegrityError):
            await conn.execute(
                insert(Account).values(
                    group_id=group_id,
                    role="owner",
                    email=f"{uuid.uuid4().hex}@x.com",
                    password_hash="x",
                )
            )
        await conn.rollback()


@pytest.mark.asyncio
async def test_deleting_an_account_removes_what_it_owns(engine):
    async with engine.begin() as conn:
        _, owner_id = await _new_group_with_owner(conn, f"{uuid.uuid4().hex}@example.com")
        workspace_id = uuid.uuid4()
        await conn.execute(
            insert(Workspace).values(id=workspace_id, account_id=owner_id, name="Mặc định")
        )
        await conn.execute(insert(Session).values(workspace_id=workspace_id))
        await conn.execute(delete(Account).where(Account.id == owner_id))
        remaining = await conn.execute(select(Session).where(Session.workspace_id == workspace_id))
        assert remaining.first() is None


@pytest.mark.asyncio
async def test_deleting_a_path_keeps_its_sessions(engine):
    async with engine.begin() as conn:
        _, owner_id = await _new_group_with_owner(conn, f"{uuid.uuid4().hex}@example.com")
        workspace_id, path_id, session_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        await conn.execute(insert(Workspace).values(id=workspace_id, account_id=owner_id, name="W"))
        await conn.execute(insert(LearningPath).values(id=path_id, workspace_id=workspace_id))
        await conn.execute(
            insert(Session).values(id=session_id, workspace_id=workspace_id, path_id=path_id)
        )
        await conn.execute(delete(LearningPath).where(LearningPath.id == path_id))
        path = await conn.scalar(select(Session.path_id).where(Session.id == session_id))
        assert path is None


def test_downgrade_removes_every_table(database_url, alembic_config):
    config = alembic_config(database_url)
    command.downgrade(config, "base")
    try:
        engine = create_async_engine(database_url)
        assert asyncio.run(_dispose_after(engine, _tables(engine))) == set()
    finally:
        command.upgrade(config, "head")


async def _dispose_after(engine, coro):
    try:
        return await coro
    finally:
        await engine.dispose()
