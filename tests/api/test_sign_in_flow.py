"""F01 end to end through the real app: sign-in by email, session, profile, avatar,
per-account interface settings and per-account data directories."""

from fastapi.testclient import TestClient
import pytest

from tests.conftest import new_learner, new_owner, run_in_db

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


@pytest.fixture(scope="module")
def app():
    from masterly.api.main import app as fastapi_app

    return fastapi_app


@pytest.fixture(scope="module")
def people(app):
    from tests.conftest import _DB_UNAVAILABLE

    if _DB_UNAVAILABLE is not None:
        pytest.skip("PostgreSQL is not reachable")
    owner = new_owner("Chu.Nhom@Example.com", "owner-pass")
    learner = new_learner(owner.group_id, "hoc@example.com", "hoc-pass")
    return {"owner": owner, "learner": learner}


def _login(client: TestClient, email: str, password: str):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def test_pages_need_a_session(app, needs_db):
    with TestClient(app) as client:
        assert client.get("/api/auth/status").json()["authenticated"] is False
        assert client.get("/api/auth/profile").status_code == 401
        assert client.put("/api/settings/ui", json={"theme": "dark"}).status_code == 401


def test_wrong_credentials_are_refused(app, people):
    with TestClient(app) as client:
        assert _login(client, "chu.nhom@example.com", "wrong").status_code == 401
        assert _login(client, "nobody@example.com", "x").status_code == 401


def test_owner_signs_in_by_email_in_any_case(app, people):
    with TestClient(app) as client:
        resp = _login(client, "chu.nhom@EXAMPLE.com", "owner-pass")
        assert resp.status_code == 200
        assert resp.json()["is_owner"] is True
        assert "masterly_token" in resp.cookies

        status = client.get("/api/auth/status").json()
        assert status["authenticated"] is True
        assert status["role"] == "owner"
        assert status["email"] == "Chu.Nhom@Example.com"

        profile = client.get("/api/auth/profile").json()
        assert profile["id"] == str(people["owner"].id)
        assert profile["display_name"] == "Chu.Nhom"
        assert profile["created_at"]


def test_learner_is_not_an_owner(app, people):
    with TestClient(app) as client:
        resp = _login(client, "hoc@example.com", "hoc-pass")
        assert resp.json()["is_owner"] is False
        assert client.get("/api/auth/status").json()["role"] == "learner"


def test_a_disabled_account_loses_its_session(app, people):
    from sqlalchemy import update

    from masterly.db.models import Account

    learner = new_learner(people["owner"].group_id)
    with TestClient(app) as client:
        assert _login(client, learner.email, "learner-pass").status_code == 200
        run_in_db(
            lambda s: s.execute(update(Account).where(Account.id == learner.id).values(disabled=True))
        )
        assert client.get("/api/auth/status").json()["authenticated"] is False
        assert _login(client, learner.email, "learner-pass").status_code == 401


def test_avatar_icon_upload_and_removal(app, people):
    with TestClient(app) as client:
        _login(client, "hoc@example.com", "hoc-pass")
        assert client.put("/api/auth/profile", json={"avatar": "icon:star:blue"}).json()["avatar"] == "icon:star:blue"
        assert client.put("/api/auth/profile", json={"avatar": "javascript:x"}).status_code == 422

        uploaded = client.put("/api/auth/profile/avatar", files={"file": ("a.png", PNG, "image/png")})
        assert uploaded.json()["avatar"] == "img:1"
        again = client.put("/api/auth/profile/avatar", files={"file": ("a.png", PNG, "image/png")})
        assert again.json()["avatar"] == "img:2"
        user_id = client.get("/api/auth/status").json()["user_id"]
        image = client.get(f"/api/auth/avatar/{user_id}")
        assert image.status_code == 200
        assert image.headers["content-type"] == "image/png"

        svg = client.put("/api/auth/profile/avatar", files={"file": ("a.svg", b"<svg/>", "image/svg+xml")})
        assert svg.status_code == 415

        assert client.delete("/api/auth/profile/avatar").json()["avatar"] == ""
        assert client.get(f"/api/auth/avatar/{user_id}").status_code == 404


def test_avatars_are_visible_only_inside_the_group(app, people):
    other_owner = new_owner()
    with TestClient(app) as client:
        _login(client, other_owner.email, "owner-pass")
        client.put("/api/auth/profile/avatar", files={"file": ("a.png", PNG, "image/png")})
        client.post("/api/auth/logout")

        _login(client, "hoc@example.com", "hoc-pass")
        assert client.get(f"/api/auth/avatar/{other_owner.id}").status_code == 404
        assert client.get("/api/auth/avatar/not-a-uuid").status_code == 404


def test_logout_ends_the_session(app, people):
    with TestClient(app) as client:
        _login(client, "hoc@example.com", "hoc-pass")
        client.post("/api/auth/logout")
        assert client.get("/api/auth/status").json()["authenticated"] is False


def test_interface_settings_are_per_account(app, people):
    with TestClient(app) as client:
        assert client.get("/api/settings/ui").json() == {"theme": "light", "language": "vi"}

        _login(client, "hoc@example.com", "hoc-pass")
        saved = client.put("/api/settings/ui", json={"theme": "dark", "language": "en"}).json()
        assert saved == {"theme": "dark", "language": "en"}
        assert client.get("/api/settings/ui").json() == saved
        assert client.put("/api/settings/ui", json={"language": "vi"}).json() == {
            "theme": "dark",
            "language": "vi",
        }
        assert client.put("/api/settings/ui", json={"theme": "glass"}).status_code == 422

        client.post("/api/auth/logout")
        _login(client, "chu.nhom@example.com", "owner-pass")
        assert client.get("/api/settings/ui").json() == {"theme": "light", "language": "vi"}


def test_each_account_has_its_own_data_directory(people):
    from masterly.multi_user.context import current_user_for, reset_current_user, set_current_user
    from masterly.services.path_service import get_path_service

    def workspace_of(account):
        token = set_current_user(current_user_for(account))
        try:
            return get_path_service().get_workspace_dir()
        finally:
            reset_current_user(token)

    learner_dir = workspace_of(people["learner"])
    owner_dir = workspace_of(people["owner"])

    assert str(people["learner"].id) in learner_dir.parts
    assert str(people["owner"].id) in owner_dir.parts
    assert learner_dir != owner_dir
