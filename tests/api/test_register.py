"""Registering creates a group with its owner and a default space, and signs in."""

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, select

from masterly.db.models import Account, Workspace
from tests.conftest import run_in_db


@pytest.fixture(scope="module")
def app():
    from masterly.api.main import app as fastapi_app

    return fastapi_app


def _register(client, email, password="secret-pass", **extra):
    return client.post("/api/auth/register", json={"email": email, "password": password, **extra})


def test_registering_creates_an_owner_and_signs_in(app, needs_db):
    with TestClient(app) as client:
        resp = _register(client, "moi@example.com", display_name="Cô Lan")
        assert resp.status_code == 201
        assert resp.json()["is_owner"] is True
        assert "masterly_token" in resp.cookies

        status = client.get("/api/auth/status").json()
        assert status["authenticated"] is True
        assert status["role"] == "owner"
        assert status["display_name"] == "Cô Lan"

    async def counts(session):
        account = await session.scalar(select(Account).where(Account.email == "moi@example.com"))
        spaces = await session.scalar(
            select(func.count()).select_from(Workspace).where(Workspace.account_id == account.id)
        )
        return account, spaces

    account, spaces = run_in_db(counts)
    assert account.role == "owner"
    assert spaces == 1


def test_each_registration_gets_its_own_group(app, needs_db):
    with TestClient(app) as client:
        first = _register(client, "a-group@example.com").json()
        second = _register(client, "b-group@example.com").json()
    groups = run_in_db(
        lambda s: s.scalars(
            select(Account.group_id).where(Account.id.in_([first["user_id"], second["user_id"]]))
        )
    )
    assert len(set(groups.all())) == 2


def test_an_email_registers_once_regardless_of_case(app, needs_db):
    with TestClient(app) as client:
        assert _register(client, "Trung@Example.com").status_code == 201
        again = _register(client, "trung@example.COM")
        assert again.status_code == 409


@pytest.mark.parametrize(
    "body",
    [
        {"email": "not-an-email", "password": "secret-pass"},
        {"email": "short@example.com", "password": "1234567"},
        {"email": "long@example.com", "password": "x" * 73},
    ],
)
def test_invalid_registrations_are_refused(app, needs_db, body):
    with TestClient(app) as client:
        assert client.post("/api/auth/register", json=body).status_code == 422


def test_a_registered_owner_can_sign_in_later(app, needs_db):
    with TestClient(app) as client:
        _register(client, "later@example.com", "later-pass")
        client.post("/api/auth/logout")
        resp = client.post("/api/auth/login", json={"email": "later@example.com", "password": "later-pass"})
        assert resp.status_code == 200
