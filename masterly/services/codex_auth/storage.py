"""Private, generation-safe storage for Masterly Codex credentials."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import threading
from typing import Any, BinaryIO

from .contracts import CatalogSnapshot, CodexAuthError, CodexCredentials

_SCHEMA_VERSION = 1


def _is_reparse_point(path: Path) -> bool:
    try:
        attributes = getattr(os.lstat(path), "st_file_attributes", 0)
    except FileNotFoundError:
        return False
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def _unsafe_path() -> CodexAuthError:
    return CodexAuthError(
        "unsafe_storage_path",
        "Codex authentication storage uses an unsafe filesystem path.",
        500,
    )


def _assert_safe_directory(path: Path) -> None:
    if path.is_symlink() or _is_reparse_point(path):
        raise _unsafe_path()
    if path.exists() and not path.is_dir():
        raise _unsafe_path()


def _assert_safe_regular_path(path: Path) -> None:
    _assert_safe_directory(path.parent)
    if path.is_symlink() or _is_reparse_point(path):
        raise _unsafe_path()
    if path.exists() and not path.is_file():
        raise _unsafe_path()


@contextmanager
def _locked_file(path: Path) -> Iterator[BinaryIO]:
    _assert_safe_regular_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        # ``sys.platform`` rather than ``os.name``: the checker narrows on it,
        # so the Windows-only ``msvcrt`` branch type-checks off Windows too.
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield handle
        finally:
            handle.seek(0)
            if sys.platform == "win32":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    _assert_safe_regular_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_path, stat.S_IRUSR | stat.S_IWUSR)
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


# The three parts a store keeps, and the error a damaged copy of each raises.
_PARTS = {
    "state": ("state_corrupt", "Stored Codex authentication state is invalid."),
    "credentials": ("credential_corrupt", "Stored Codex credentials are invalid."),
    "catalog_cache": ("catalog_corrupt", "Stored Codex model data is invalid."),
}


class _Document:
    """The parts of one store, read and written while its lock is held."""

    def get(self, part: str) -> dict[str, Any] | None:
        raise NotImplementedError

    def set(self, part: str, payload: Mapping[str, Any] | None) -> None:
        """Replace a part; ``None`` removes it."""
        raise NotImplementedError


class BaseCredentialStore:
    """Generation-safe credential logic over any locked document backend.

    Every login, refresh and logout bumps a generation. A write carries the
    generation it started from and is refused once another one has landed, so
    a slow refresh can never bring back credentials a logout removed.
    """

    @contextmanager
    def _locked(self) -> Iterator[_Document]:
        raise NotImplementedError
        yield  # pragma: no cover

    def assert_safe_location(self) -> None:
        """Raise :class:`CodexAuthError` if the store's location is unsafe."""

    @staticmethod
    def _state(document: _Document) -> dict[str, Any]:
        state = document.get("state")
        if state is None:
            return {"schema_version": _SCHEMA_VERSION, "generation": 0}
        generation = state.get("generation")
        if isinstance(generation, bool) or not isinstance(generation, int) or generation < 0:
            raise CodexAuthError(*_PARTS["state"], 500)
        return state

    @staticmethod
    def _generation_changed() -> CodexAuthError:
        return CodexAuthError(
            "generation_changed",
            "Codex authentication changed while this operation was running.",
            409,
        )

    @staticmethod
    def _bump(document: _Document, state: dict[str, Any]) -> int:
        next_generation = int(state["generation"]) + 1
        document.set(
            "state",
            {**state, "schema_version": _SCHEMA_VERSION, "generation": next_generation},
        )
        return next_generation

    def current_generation(self) -> int:
        with self._locked() as document:
            return int(self._state(document)["generation"])

    def load_credentials(self) -> CodexCredentials | None:
        with self._locked() as document:
            state_generation = int(self._state(document)["generation"])
            payload = document.get("credentials")
            if payload is None:
                return None
            credentials = CodexCredentials.from_dict(payload)
            if credentials.generation != state_generation:
                return None
            return credentials

    def commit_credentials(
        self,
        credentials: CodexCredentials,
        expected_generation: int,
    ) -> CodexCredentials:
        with self._locked() as document:
            state = self._state(document)
            if int(state["generation"]) != expected_generation:
                raise self._generation_changed()
            next_generation = self._bump(document, state)
            committed = replace(
                credentials,
                schema_version=_SCHEMA_VERSION,
                generation=next_generation,
            )
            document.set("credentials", committed.to_dict())
            return committed

    def clear_credentials(self, expected_generation: int | None = None) -> int:
        with self._locked() as document:
            state = self._state(document)
            if expected_generation is not None and int(state["generation"]) != expected_generation:
                raise self._generation_changed()
            next_generation = self._bump(document, state)
            document.set("credentials", None)
            document.set("catalog_cache", None)
            return next_generation

    def load_catalog_cache(self) -> dict[str, Any] | None:
        with self._locked() as document:
            return document.get("catalog_cache")

    def save_catalog_cache(self, payload: Mapping[str, Any]) -> None:
        with self._locked() as document:
            document.set("catalog_cache", payload)

    def commit_catalog_cache(self, snapshot: CatalogSnapshot) -> None:
        """Publish a response only while its credential owner and generation are current.

        Validation and publication share logout's lock. Checking before taking
        it would let a late 200 or 304 response recreate a cache cleared by
        logout or overwrite a newer account's version history.
        """
        with self._locked() as document:
            generation = int(self._state(document)["generation"])
            if generation != snapshot.generation:
                raise self._generation_changed()
            payload = document.get("credentials")
            if payload is None:
                raise self._generation_changed()
            credentials = CodexCredentials.from_dict(payload)
            account_hash = hashlib.sha256(credentials.account_id.encode("utf-8")).hexdigest()
            if credentials.generation != generation or account_hash != snapshot.account_hash:
                raise self._generation_changed()
            document.set("catalog_cache", snapshot.to_dict())

    def invalidate_catalog_models(self, account_hash: str, *, generation: int) -> None:
        """Atomically invalidate matching models, retaining successful version history.

        Matching and rewriting share the lock with logout, so an in-flight auth
        error cannot recreate a cache that logout cleared. A response for an
        older account or generation cannot invalidate a newer catalog either.
        """
        with self._locked() as document:
            try:
                payload = document.get("catalog_cache")
                if payload is None:
                    return
                snapshot = CatalogSnapshot.from_dict(payload)
            except CodexAuthError as exc:
                if exc.code != "catalog_corrupt":
                    raise
                document.set("catalog_cache", None)
                return
            if snapshot.account_hash != account_hash or snapshot.generation != generation:
                return
            if snapshot.client_version is None:
                document.set("catalog_cache", None)
                return
            document.set(
                "catalog_cache",
                replace(snapshot, models=(), etag=None, models_valid=False).to_dict(),
            )

    def clear_catalog_cache(self) -> None:
        with self._locked() as document:
            document.set("catalog_cache", None)


class _FileDocument(_Document):
    def __init__(self, paths: dict[str, Path]) -> None:
        self._paths = paths

    def get(self, part: str) -> dict[str, Any] | None:
        path = self._paths[part]
        code, message = _PARTS[part]
        _assert_safe_regular_path(path)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CodexAuthError(code, message, 500) from exc
        if not isinstance(payload, dict):
            raise CodexAuthError(code, message, 500)
        return payload

    def set(self, part: str, payload: Mapping[str, Any] | None) -> None:
        path = self._paths[part]
        if payload is None:
            _assert_safe_regular_path(path)
            path.unlink(missing_ok=True)
        else:
            _atomic_write_json(path, payload)


class CodexCredentialStore(BaseCredentialStore):
    """Store credentials as private files below an explicitly supplied root.

    For code that runs with no group (tests, scripts); a group keeps its login
    in its database row (``GroupCodexStore``).
    """

    def __init__(self, user_root: Path) -> None:
        self.root = Path(user_root) / "private" / "openai-codex"
        self.credentials_path = self.root / "credentials.v1.json"
        self.state_path = self.root / "state.v1.json"
        self.catalog_cache_path = self.root / "models-cache.v1.json"
        self.lock_path = self.root / "auth.lock"
        self._thread_lock = threading.Lock()

    def assert_safe_location(self) -> None:
        """Raise :class:`CodexAuthError` unless this store sits on plain dirs.

        Both levels are checked, and the parent is the one that matters: a
        symlink there would silently redirect the whole store — reading, and
        worse, relocating — to someone else's credentials.
        """
        _assert_safe_directory(self.root.parent)
        _assert_safe_directory(self.root)

    def _ensure_root(self) -> None:
        private_root = self.root.parent
        private_root.mkdir(parents=True, exist_ok=True)
        _assert_safe_directory(private_root)
        self.root.mkdir(exist_ok=True)
        _assert_safe_directory(self.root)
        os.chmod(private_root, stat.S_IRWXU)
        os.chmod(self.root, stat.S_IRWXU)

    @contextmanager
    def _locked(self) -> Iterator[_Document]:
        with self._thread_lock:
            self._ensure_root()
            with _locked_file(self.lock_path):
                yield _FileDocument(
                    {
                        "state": self.state_path,
                        "credentials": self.credentials_path,
                        "catalog_cache": self.catalog_cache_path,
                    }
                )
