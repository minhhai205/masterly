"""A throwaway PostgreSQL database per test module, migrated to the latest schema.

Uses the server from the ``DB_*`` settings (``docker compose up -d db``). When no
server answers, the database tests are skipped rather than failed.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path
import uuid

from alembic import command
from alembic.config import Config
import asyncpg
import pytest
from sqlalchemy.engine import URL

from masterly.db.config import PROJECT_ROOT, get_database_settings


def _admin_dsn() -> str:
    settings = get_database_settings()
    url = settings.url(database="postgres").set(drivername="postgresql")
    return url.render_as_string(hide_password=False)


async def _execute(sql: str) -> None:
    connection = await asyncpg.connect(_admin_dsn(), timeout=3)
    try:
        await connection.execute(sql)
    finally:
        await connection.close()


def _alembic_config(url: URL) -> Config:
    config = Config(str(Path(PROJECT_ROOT) / "alembic.ini"))
    config.attributes["connection_url"] = url
    config.attributes["configure_logger"] = False
    return config


@pytest.fixture
def alembic_config():
    """Build an Alembic config pointed at a given database URL."""
    return _alembic_config


@pytest.fixture(scope="module")
def database_url() -> Iterator[URL]:
    name = f"masterly_test_{uuid.uuid4().hex[:12]}"
    try:
        asyncio.run(_execute(f'CREATE DATABASE "{name}"'))
    except (OSError, asyncpg.PostgresError, asyncio.TimeoutError) as exc:
        pytest.skip(f"PostgreSQL is not reachable ({exc}); run `docker compose up -d db`")
    url = get_database_settings().url(database=name)
    command.upgrade(_alembic_config(url), "head")
    try:
        yield url
    finally:
        asyncio.run(_execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
