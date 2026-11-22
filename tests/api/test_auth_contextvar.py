"""The current user set by require_auth must reach the endpoint.

A sync dependency runs in a worker thread under a copy of the request context,
so a ContextVar set there is lost; data paths would then resolve to the wrong
account.
"""

from __future__ import annotations

import inspect

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient


def test_guards_are_async_def() -> None:
    from masterly.api.routers.auth import optional_auth, require_admin, require_auth

    assert inspect.iscoroutinefunction(require_auth)
    assert inspect.iscoroutinefunction(require_admin)
    assert inspect.iscoroutinefunction(optional_auth)


def test_require_auth_propagates_user_contextvar_to_endpoint(monkeypatch) -> None:
    from masterly.api.routers import auth as auth_router
    from masterly.multi_user.context import get_current_user_or_none
    from masterly.services.auth import TokenPayload

    monkeypatch.setattr(
        auth_router,
        "decode_token",
        lambda _t: TokenPayload(username="alice", role="user", user_id="u_alice"),
    )
    app = FastAPI()

    @app.get("/whoami")
    async def whoami(_=Depends(auth_router.require_auth)) -> dict:
        user = get_current_user_or_none()
        if user is None:
            return {"seen": None}
        return {"seen": user.username, "role": user.role, "scope_kind": user.scope.kind}

    with TestClient(app) as client:
        resp = client.get("/whoami", headers={"Authorization": "Bearer test-token"})

    assert resp.status_code == 200
    assert resp.json() == {"seen": "alice", "role": "user", "scope_kind": "user"}


def test_require_admin_refuses_learners(monkeypatch) -> None:
    from masterly.api.routers import auth as auth_router
    from masterly.services.auth import TokenPayload

    monkeypatch.setattr(
        auth_router,
        "decode_token",
        lambda _t: TokenPayload(username="alice", role="user", user_id="u_alice"),
    )
    app = FastAPI()

    @app.get("/admin-only")
    async def admin_only(_=Depends(auth_router.require_admin)) -> dict:
        return {"ok": True}

    with TestClient(app) as client:
        resp = client.get("/admin-only", headers={"Authorization": "Bearer test-token"})

    assert resp.status_code == 403


def test_path_service_resolves_per_user_workspace_through_dependency(monkeypatch, tmp_path) -> None:
    from masterly.api.routers import auth as auth_router
    from masterly.multi_user import paths as mu_paths
    from masterly.services.auth import TokenPayload
    from masterly.services.path_service import get_path_service

    monkeypatch.setattr(mu_paths, "USERS_ROOT", tmp_path / "data" / "users")
    monkeypatch.setattr(mu_paths, "_path_services", {})
    monkeypatch.setattr(
        auth_router,
        "decode_token",
        lambda _t: TokenPayload(username="alice", role="user", user_id="u_alice"),
    )
    app = FastAPI()

    @app.get("/db-path")
    async def db_path(_=Depends(auth_router.require_auth)) -> dict:
        return {"chat_db": str(get_path_service().get_chat_history_db())}

    with TestClient(app) as client:
        resp = client.get("/db-path", headers={"Authorization": "Bearer test-token"})

    assert resp.status_code == 200
    expected_root = str((tmp_path / "data" / "users" / "u_alice").resolve())
    assert resp.json()["chat_db"].startswith(expected_root)
