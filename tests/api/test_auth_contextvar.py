"""The current user set by require_auth must reach the endpoint.

A sync dependency runs in a worker thread under a copy of the request context,
so a ContextVar set there is lost; data paths would then resolve to the wrong
account.
"""

from __future__ import annotations

import inspect
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from masterly.multi_user.models import CurrentUser, UserScope


def _user(role: str, root: Path = Path("/tmp/masterly-u_alice")) -> CurrentUser:
    return CurrentUser(
        id="u_alice",
        email="alice@example.com",
        display_name="alice",
        role=role,  # type: ignore[arg-type]
        group_id="g_1",
        scope=UserScope(kind="user", user_id="u_alice", root=root),
    )


def _signed_in_as(monkeypatch, user: CurrentUser) -> None:
    from masterly.api.routers import auth as auth_router

    async def fake(_token):
        return user

    monkeypatch.setattr(auth_router, "_signed_in_user", fake)


def test_guards_are_async_def() -> None:
    from masterly.api.routers.auth import optional_auth, require_auth, require_owner

    assert inspect.iscoroutinefunction(require_auth)
    assert inspect.iscoroutinefunction(require_owner)
    assert inspect.iscoroutinefunction(optional_auth)


def test_require_auth_propagates_user_contextvar_to_endpoint(monkeypatch) -> None:
    from masterly.api.routers import auth as auth_router
    from masterly.multi_user.context import get_current_user_or_none

    _signed_in_as(monkeypatch, _user("learner"))
    app = FastAPI()

    @app.get("/whoami")
    async def whoami(_=Depends(auth_router.require_auth)) -> dict:
        user = get_current_user_or_none()
        if user is None:
            return {"seen": None}
        return {"seen": user.email, "role": user.role, "scope_kind": user.scope.kind}

    with TestClient(app) as client:
        resp = client.get("/whoami", headers={"Authorization": "Bearer test-token"})

    assert resp.status_code == 200
    assert resp.json() == {"seen": "alice@example.com", "role": "learner", "scope_kind": "user"}


def test_require_owner_refuses_learners(monkeypatch) -> None:
    from masterly.api.routers import auth as auth_router

    _signed_in_as(monkeypatch, _user("learner"))
    app = FastAPI()

    @app.get("/owner-only")
    async def owner_only(_=Depends(auth_router.require_owner)) -> dict:
        return {"ok": True}

    with TestClient(app) as client:
        assert client.get("/owner-only", headers={"Authorization": "Bearer t"}).status_code == 403


def test_path_service_resolves_per_user_workspace_through_dependency(monkeypatch, tmp_path) -> None:
    from masterly.api.routers import auth as auth_router
    from masterly.multi_user import paths as mu_paths
    from masterly.services.path_service import get_path_service

    user_root = (tmp_path / "data" / "users" / "u_alice").resolve()
    monkeypatch.setattr(mu_paths, "_path_services", {})
    _signed_in_as(monkeypatch, _user("learner", user_root))
    app = FastAPI()

    @app.get("/db-path")
    async def db_path(_=Depends(auth_router.require_auth)) -> dict:
        return {"chat_db": str(get_path_service().get_chat_history_db())}

    with TestClient(app) as client:
        resp = client.get("/db-path", headers={"Authorization": "Bearer test-token"})

    assert resp.status_code == 200
    assert resp.json()["chat_db"].startswith(str(user_root))
