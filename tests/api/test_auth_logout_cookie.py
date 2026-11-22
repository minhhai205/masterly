"""The deleting Set-Cookie must carry the same attributes as the one that set it,
or browsers keep the old session cookie."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_logout_sets_secure_when_cookie_secure_enabled(monkeypatch) -> None:
    from masterly.api.routers import auth as auth_router

    monkeypatch.setattr(auth_router, "_SECURE", True)
    monkeypatch.setattr(auth_router, "_SAMESITE", "none")
    app = FastAPI()
    app.add_api_route("/logout", auth_router.logout, methods=["POST"])

    with TestClient(app) as client:
        resp = client.post("/logout")

    set_cookie = resp.headers.get("set-cookie", "").lower()
    assert resp.status_code == 200
    assert "max-age=0" in set_cookie
    assert "samesite=none" in set_cookie
    assert "secure" in set_cookie


def test_logout_omits_secure_when_cookie_secure_disabled(monkeypatch) -> None:
    from masterly.api.routers import auth as auth_router

    monkeypatch.setattr(auth_router, "_SECURE", False)
    monkeypatch.setattr(auth_router, "_SAMESITE", "lax")
    app = FastAPI()
    app.add_api_route("/logout", auth_router.logout, methods=["POST"])

    with TestClient(app) as client:
        resp = client.post("/logout")

    set_cookie = resp.headers.get("set-cookie", "").lower()
    assert "max-age=0" in set_cookie
    assert "samesite=lax" in set_cookie
    assert "secure" not in set_cookie
