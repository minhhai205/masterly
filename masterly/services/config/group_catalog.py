"""Each group's model catalog, kept in ``groups.model_catalog``.

A group's catalog is read on almost every model call, so the backend keeps the
decrypted copy in memory per group and goes back to the database only when the
row's ``catalog_revision`` moves. Every sign-in check compares that revision
(``refresh_group_catalog``); a save writes the row, bumps the revision and
updates the copy here in the same step.

Credentials are encrypted value by value before they are written, and decrypted
only into this in-memory copy (see ``masterly.services.encryption``).
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import logging
import threading
from typing import Any
import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from masterly.db.blocking import run_blocking
from masterly.db.models import Group
from masterly.services.encryption import decrypt_text, encrypt_text

from .model_catalog import ModelCatalogService, map_catalog_secrets

logger = logging.getLogger(__name__)


@dataclass
class _Entry:
    revision: int
    catalog: dict[str, Any]


_cache: dict[str, _Entry] = {}
_cache_lock = threading.Lock()
_services: dict[str, GroupCatalogService] = {}


def _decrypted(stored: dict[str, Any] | None) -> dict[str, Any]:
    return map_catalog_secrets(stored or {}, decrypt_text)


async def _read_row(session: AsyncSession, group_id: str) -> _Entry:
    row = (
        await session.execute(
            select(Group.catalog_revision, Group.model_catalog).where(
                Group.id == uuid.UUID(group_id)
            )
        )
    ).one_or_none()
    if row is None:
        return _Entry(revision=0, catalog={})
    return _Entry(revision=row.catalog_revision, catalog=_decrypted(row.model_catalog))


def _remember(group_id: str, entry: _Entry) -> None:
    with _cache_lock:
        _cache[group_id] = entry


def _forget_runtime_clients(group_id: str) -> None:
    """Drop the clients and resolved configs built from a group's old catalog."""
    from masterly.services.embedding.client import reset_embedding_client
    from masterly.services.llm.client import reset_llm_client
    from masterly.services.llm.config import clear_llm_config_cache

    clear_llm_config_cache(group_id)
    reset_llm_client(group_id)
    reset_embedding_client(group_id)


async def refresh_group_catalog(session: AsyncSession, group_id: str) -> None:
    """Bring this process's copy of a group's catalog up to the stored revision.

    Cheap when nothing changed: one indexed read of an integer.
    """
    revision = await session.scalar(
        select(Group.catalog_revision).where(Group.id == uuid.UUID(group_id))
    )
    with _cache_lock:
        cached = _cache.get(group_id)
    if cached is not None and cached.revision == revision:
        return
    _remember(group_id, await _read_row(session, group_id))
    if cached is not None:
        logger.info("Catalog of group %s changed elsewhere; reloading its clients", group_id)
        _forget_runtime_clients(group_id)


class GroupCatalogService(ModelCatalogService):
    """The model catalog of one group, stored in its ``groups`` row."""

    def __init__(self, group_id: str):
        super().__init__(path=None)
        self.group_id = group_id
        self.path = None  # type: ignore[assignment]  # no file behind a group catalog

    @property
    def location(self) -> str:
        return f"group {self.group_id}"

    def _read_existing_catalog(self) -> dict[str, Any]:
        with _cache_lock:
            entry = _cache.get(self.group_id)
        if entry is None:
            # Outside a signed-in request nothing has refreshed this group yet,
            # e.g. a background job resumed after a restart.
            entry = run_blocking(lambda session: _read_row(session, self.group_id))
            _remember(self.group_id, entry)
        return deepcopy(entry.catalog)

    def _write(self, normalized: dict[str, Any]) -> None:
        stored = map_catalog_secrets(normalized, encrypt_text)

        async def write(session: AsyncSession) -> int:
            return (
                await session.execute(
                    update(Group)
                    .where(Group.id == uuid.UUID(self.group_id))
                    .values(model_catalog=stored, catalog_revision=Group.catalog_revision + 1)
                    .returning(Group.catalog_revision)
                )
            ).scalar_one()

        revision = run_blocking(write)
        _remember(self.group_id, _Entry(revision=revision, catalog=deepcopy(normalized)))


def get_group_catalog_service(group_id: str) -> GroupCatalogService:
    service = _services.get(group_id)
    if service is None:
        service = _services.setdefault(group_id, GroupCatalogService(group_id))
    return service


__all__ = ["GroupCatalogService", "get_group_catalog_service", "refresh_group_catalog"]
