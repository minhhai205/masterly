"""Data models of the signed-in account and its data scope."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Role = Literal["owner", "learner"]
ScopeKind = Literal["admin", "user"]


@dataclass(frozen=True, slots=True)
class UserScope:
    kind: ScopeKind
    user_id: str
    root: Path

    @property
    def cache_key(self) -> str:
        return f"{self.kind}:{self.user_id}:{self.root.resolve()}"


@dataclass(frozen=True, slots=True)
class CurrentUser:
    """The signed-in account, loaded from the database once per request."""

    id: str
    email: str
    display_name: str
    role: Role
    group_id: str
    scope: UserScope
    avatar: str = ""
    theme: str = "light"
    language: str = "vi"
    created_at: str = ""

    @property
    def is_owner(self) -> bool:
        return self.role == "owner"


LOCAL_ADMIN_ID = "local-admin"
