"""F01 end to end through the real app: sign-in, session, profile, avatar,
per-account interface settings and per-account data directories."""

from fastapi.testclient import TestClient
import pytest

from tests.conftest import ADMIN_PASSWORD, ADMIN_USERNAME

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


@pytest.fixture(scope="module")
def app():
    from masterly.api.main import app as fastapi_app
    from masterly.services.auth import add_user

    add_user("hoc", "hoc-pass")
    return fastapi_app


def _login(client: TestClient, username: str, password: str):
    return client.post("/api/auth/login", json={"username": username, "password": password})


def test_pages_need_a_session(app):
    with TestClient(app) as client:
        assert client.get("/api/auth/status").json()["authenticated"] is False
        assert client.get("/api/auth/profile").status_code == 401
        assert client.put("/api/settings/ui", json={"theme": "dark"}).status_code == 401


def test_wrong_password_is_refused(app):
    with TestClient(app) as client:
        assert _login(client, ADMIN_USERNAME, "wrong").status_code == 401
        assert _login(client, "nobody", "x").status_code == 401


def test_declared_admin_signs_in_and_owns_a_profile(app):
    with TestClient(app) as client:
        resp = _login(client, ADMIN_USERNAME, ADMIN_PASSWORD)
        assert resp.status_code == 200
        assert resp.json()["is_admin"] is True
        assert "masterly_token" in resp.cookies

        profile = client.get("/api/auth/profile").json()
        assert profile["role"] == "admin"
        assert profile["id"].startswith("u_")
        assert profile["created_at"]


def test_avatar_icon_upload_and_removal(app):
    with TestClient(app) as client:
        _login(client, ADMIN_USERNAME, ADMIN_PASSWORD)
        assert client.put("/api/auth/profile", json={"avatar": "icon:star:blue"}).json()["avatar"] == "icon:star:blue"
        assert client.put("/api/auth/profile", json={"avatar": "javascript:x"}).status_code == 422

        uploaded = client.put("/api/auth/profile/avatar", files={"file": ("a.png", PNG, "image/png")})
        assert uploaded.json()["avatar"].startswith("img:")
        user_id = client.get("/api/auth/status").json()["user_id"]
        assert client.get(f"/api/auth/avatar/{user_id}").status_code == 200

        svg = client.put("/api/auth/profile/avatar", files={"file": ("a.svg", b"<svg/>", "image/svg+xml")})
        assert svg.status_code == 415

        assert client.delete("/api/auth/profile/avatar").json()["avatar"] == ""
        assert client.get(f"/api/auth/avatar/{user_id}").status_code == 404


def test_logout_ends_the_session(app):
    with TestClient(app) as client:
        _login(client, ADMIN_USERNAME, ADMIN_PASSWORD)
        client.post("/api/auth/logout")
        assert client.get("/api/auth/status").json()["authenticated"] is False


def test_interface_settings_are_per_account(app):
    with TestClient(app) as client:
        assert client.get("/api/settings/ui").json() == {"theme": "light", "language": "vi"}

        _login(client, "hoc", "hoc-pass")
        saved = client.put("/api/settings/ui", json={"theme": "dark", "language": "en"}).json()
        assert saved == {"theme": "dark", "language": "en"}
        assert client.get("/api/settings/ui").json() == saved
        assert client.put("/api/settings/ui", json={"theme": "glass"}).status_code == 422

        client.post("/api/auth/logout")
        _login(client, ADMIN_USERNAME, ADMIN_PASSWORD)
        assert client.get("/api/settings/ui").json() == {"theme": "light", "language": "vi"}


def test_learner_data_lives_in_its_own_directory(app):
    from masterly.multi_user.context import set_current_user, user_from_token_payload
    from masterly.services.auth import authenticate
    from masterly.services.path_service import get_path_service

    set_current_user(user_from_token_payload(authenticate("hoc", "hoc-pass")))
    learner_dir = get_path_service().get_workspace_dir()
    set_current_user(user_from_token_payload(authenticate(ADMIN_USERNAME, ADMIN_PASSWORD)))
    admin_dir = get_path_service().get_workspace_dir()

    assert "users" in learner_dir.parts
    assert learner_dir != admin_dir
    assert not str(learner_dir).startswith(str(admin_dir))
