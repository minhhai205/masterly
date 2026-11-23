"""Database access for synchronous code.

Most of the backend reaches the database through ``async`` sessions. A few
callers are synchronous and run anywhere — on the event loop thread, in worker
threads, in background jobs — and still need a quick read or write: the model
catalog is the one that matters. They go through here.

The work runs on a single background thread with its own event loop and its own
engine. asyncpg connections belong to the loop that opened them, so this engine
is never shared with the request engine, and a caller on the request loop simply
waits for the result instead of re-entering its own loop.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import threading
from typing import TypeVar

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from masterly.db.config import get_database_settings

T = TypeVar("T")

_lock = threading.Lock()
_loop: asyncio.AbstractEventLoop | None = None
_sessions: async_sessionmaker[AsyncSession] | None = None


def _start() -> asyncio.AbstractEventLoop:
    global _loop, _sessions
    with _lock:
        if _loop is None:
            loop = asyncio.new_event_loop()
            threading.Thread(target=loop.run_forever, name="masterly-db", daemon=True).start()
            engine = create_async_engine(
                get_database_settings().url(), pool_pre_ping=True, pool_size=2
            )
            _sessions = async_sessionmaker(engine, expire_on_commit=False)
            _loop = loop
        return _loop


def run_blocking(work: Callable[[AsyncSession], Awaitable[T]], *, timeout: float = 15) -> T:
    """Run ``await work(session)`` on the database thread and return its result.

    The session is committed when ``work`` returns and rolled back if it raises.
    """
    loop = _start()

    async def _run() -> T:
        assert _sessions is not None
        async with _sessions() as session, session.begin():
            return await work(session)

    return asyncio.run_coroutine_threadsafe(_run(), loop).result(timeout)


__all__ = ["run_blocking"]
