"""Test setup: every run gets its own runtime home, file store and database.

Settings are read when the modules are first imported, so the environment is set
here before anything from ``masterly`` is imported. The database is a throwaway
one on the server from ``.env`` (``docker compose up -d db``), migrated to the
latest schema; without a server, tests that need it are skipped.
"""

import asyncio
import os
from pathlib import Path
import tempfile
import uuid

import pytest

_HOME = Path(tempfile.mkdtemp(prefix="masterly-test-home-"))
os.environ["MASTERLY_HOME"] = str(_HOME)
os.environ["STORAGE_BACKEND"] = "local"
os.environ["STORAGE_LOCAL_DIR"] = str(_HOME / "files")
os.environ["AUTH_SECRET"] = "test-secret-" + uuid.uuid4().hex
os.environ["DB_NAME"] = f"masterly_test_{uuid.uuid4().hex[:12]}"

from masterly.db.config import get_database_settings  # noqa: E402


def _admin_dsn() -> str:
    url = get_database_settings().url(database="postgres").set(drivername="postgresql")
    return url.render_as_string(hide_password=False)


async def _execute_on_server(sql: str) -> None:
    import asyncpg

    connection = await asyncpg.connect(_admin_dsn(), timeout=3)
    try:
        await connection.execute(sql)
    finally:
        await connection.close()


def _create_test_database() -> str | None:
    """Create and migrate the run's database; the reason it could not, or None."""
    from alembic import command
    from alembic.config import Config

    name = os.environ["DB_NAME"]
    try:
        asyncio.run(_execute_on_server(f'CREATE DATABASE "{name}"'))
    except Exception as exc:  # no server, wrong credentials…
        return str(exc) or type(exc).__name__
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.attributes["configure_logger"] = False
    command.upgrade(config, "head")
    return None


_DB_UNAVAILABLE = _create_test_database()


def pytest_sessionfinish(session, exitstatus):
    if _DB_UNAVAILABLE is None:
        name = os.environ["DB_NAME"]
        asyncio.run(_execute_on_server(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


@pytest.fixture
def needs_db():
    """Skip the test when no PostgreSQL server is reachable."""
    if _DB_UNAVAILABLE is not None:
        pytest.skip(f"PostgreSQL is not reachable ({_DB_UNAVAILABLE}); run `docker compose up -d db`")


def run_in_db(work):
    """Run ``await work(session)`` on a private engine in its own event loop, and commit.

    A private engine, because the app's engine and its connections belong to the
    loop of the running test client and must not be touched from another one.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    async def main():
        engine = create_async_engine(get_database_settings().url())
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                result = await work(session)
                await session.commit()
                return result
        finally:
            await engine.dispose()

    return asyncio.run(main())


def new_owner(email: str | None = None, password: str = "owner-pass"):
    """Create a group with its owner; returns the owner account."""
    from masterly.services.accounts import create_owner

    email = email or f"owner-{uuid.uuid4().hex[:8]}@example.com"
    return run_in_db(lambda session: create_owner(session, email, password))


def new_learner(group_id, email: str | None = None, password: str = "learner-pass"):
    """Create a learner in an existing group; returns the learner account."""
    from masterly.services.accounts import create_learner

    email = email or f"learner-{uuid.uuid4().hex[:8]}@example.com"
    return run_in_db(lambda session: create_learner(session, group_id, email, password))


# Default settings files the app writes on first start (``agents.yaml``), for
# tests that read them without starting the app.
from masterly.services.setup import ensure_agents_settings  # noqa: E402

ensure_agents_settings()
