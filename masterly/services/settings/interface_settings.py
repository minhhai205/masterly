"""Interface preferences of the current user: theme and interface language.

Stored in the user's own ``settings/interface.json``. The path is resolved on
every call, so after sign-in each account reads and writes its own file.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import json
import os
from pathlib import Path
import tempfile
import threading
from typing import Any, Literal

from masterly.services.path_service import get_path_service

UiTheme = Literal["light", "dark"]
UiLanguage = Literal["vi", "en"]

THEMES: tuple[str, ...] = ("light", "dark")
LANGUAGES: tuple[str, ...] = ("vi", "en")

DEFAULT_UI_SETTINGS: dict[str, Any] = {"theme": "light", "language": "vi"}

_LOCKS_GUARD = threading.Lock()
_LOCKS: dict[str, threading.Lock] = {}


def _settings_lock(path: Path) -> threading.Lock:
    """One lock per settings file: each account writes its own file, so unrelated
    users' writes do not wait on each other."""
    key = str(path.resolve() if path.is_absolute() else path)
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _LOCKS[key] = lock
        return lock


def _interface_settings_file() -> Path:
    return get_path_service().get_settings_file("interface")


def _normalized(stored: Mapping[str, Any]) -> dict[str, Any]:
    """Stored values merged over the defaults; unknown values fall back to them."""
    theme = stored.get("theme")
    language = stored.get("language")
    return {
        "theme": theme if theme in THEMES else DEFAULT_UI_SETTINGS["theme"],
        "language": language if language in LANGUAGES else DEFAULT_UI_SETTINGS["language"],
    }


def _read(settings_file: Path) -> dict[str, Any]:
    if not settings_file.exists():
        return {}
    try:
        with open(settings_file, encoding="utf-8") as f:
            loaded = json.load(f)
    except Exception:
        # A corrupt file reads as defaults and is replaced on the next write.
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _atomic_update(
    settings_file: Path, mutate: Callable[[dict[str, Any]], Mapping[str, Any]]
) -> dict[str, Any]:
    """Read, change and replace the file as one step. The write goes through a temp
    file and a rename, so a crash leaves the previous file, never a truncated one.
    ``mutate`` gets the raw stored mapping, not the defaults-merged view, so saving
    one field never freezes today's defaults as explicit choices."""
    with _settings_lock(settings_file):
        payload = dict(mutate(_read(settings_file)))
        settings_file.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{settings_file.name}.", suffix=".tmp", dir=settings_file.parent
        )
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, settings_file)
        finally:
            temp_path.unlink(missing_ok=True)
        return payload


def get_ui_settings() -> dict[str, Any]:
    """The current user's theme and interface language, defaults filled in."""
    return _normalized(_read(_interface_settings_file()))


def update_ui_settings(patch: Mapping[str, Any]) -> dict[str, Any]:
    """Merge ``patch`` into the stored settings and return the normalized result."""
    updates = {k: v for k, v in patch.items() if k in DEFAULT_UI_SETTINGS}

    def _mutate(stored: dict[str, Any]) -> dict[str, Any]:
        stored.update(updates)
        return stored

    return _normalized(_atomic_update(_interface_settings_file(), _mutate))
