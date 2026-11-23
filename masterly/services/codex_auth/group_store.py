"""A group's ChatGPT (Codex) login, kept encrypted in ``groups.codex_session``.

The whole store — its generation, the credentials and the model list cache — is
one JSON document, encrypted as a unit. Each operation reads it, works on it in
memory and writes it back only if the stored bytes are still the ones it read,
so two backend processes can never both commit on the same generation.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from copy import deepcopy
import json
import threading
from typing import Any
import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from masterly.db.blocking import run_blocking
from masterly.db.models import Group
from masterly.services.encryption import decrypt_bytes, encrypt_bytes

from .contracts import CodexAuthError
from .storage import _PARTS, BaseCredentialStore, _Document


class _MemoryDocument(_Document):
    def __init__(self, parts: dict[str, Any]) -> None:
        self.parts = parts

    def get(self, part: str) -> dict[str, Any] | None:
        payload = self.parts.get(part)
        if payload is not None and not isinstance(payload, dict):
            raise CodexAuthError(*_PARTS[part], 500)
        return deepcopy(payload)

    def set(self, part: str, payload: Mapping[str, Any] | None) -> None:
        if payload is None:
            self.parts.pop(part, None)
        else:
            self.parts[part] = json.loads(json.dumps(dict(payload)))


class GroupCodexStore(BaseCredentialStore):
    """The Codex login of one group."""

    def __init__(self, group_id: str) -> None:
        self.group_id = uuid.UUID(group_id)
        self._thread_lock = threading.Lock()

    def _read(self) -> bytes | None:
        async def read(session: AsyncSession) -> bytes | None:
            return await session.scalar(
                select(Group.codex_session).where(Group.id == self.group_id)
            )

        return run_blocking(read)

    def _write(self, previous: bytes | None, parts: dict[str, Any]) -> None:
        stored = encrypt_bytes(json.dumps(parts).encode()) if parts else None

        async def write(session: AsyncSession) -> int:
            result = await session.execute(
                update(Group)
                .where(
                    Group.id == self.group_id,
                    Group.codex_session.is_not_distinct_from(previous),
                )
                .values(codex_session=stored)
            )
            return result.rowcount

        if run_blocking(write) != 1:
            raise self._generation_changed()

    @contextmanager
    def _locked(self) -> Iterator[_Document]:
        with self._thread_lock:
            previous = self._read()
            try:
                parts = json.loads(decrypt_bytes(previous)) if previous else {}
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise CodexAuthError(*_PARTS["credentials"], 500) from exc
            if not isinstance(parts, dict):
                raise CodexAuthError(*_PARTS["credentials"], 500)
            document = _MemoryDocument(deepcopy(parts))
            yield document
            if document.parts != parts:
                self._write(previous, document.parts)


__all__ = ["GroupCodexStore"]
