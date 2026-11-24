"""Reading conversations through the API, as the signed-in account only."""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient
import pytest

from masterly.db.engine import dispose_engine
from masterly.services.session.store import ChatStore
from tests.conftest import new_learner, new_owner


@pytest.fixture(scope="module")
def app():
    from masterly.api.main import app as fastapi_app

    return fastapi_app


def _seed(account) -> tuple[str, int]:
    """One conversation with a finished question and answer."""

    async def work():
        try:
            store = ChatStore(account.id)
            sid = (await store.create_session("Leaves"))["id"]
            await store.add_message(sid, "user", "How do leaves make sugar?")
            turn = await store.begin_turn(sid, "chat")
            await store.append_events(turn["id"], [{"type": "content", "content": "Light"}, {"type": "done"}])
            answer = await store.add_message(sid, "assistant", "With light.")
            await store.link_turn_message(turn["id"], answer)
            await store.transition_turn(turn["id"], "completed")
            return sid, answer
        finally:
            await dispose_engine()

    return asyncio.run(work())


def _login(client: TestClient, email: str, password: str) -> None:
    assert client.post("/api/auth/login", json={"email": email, "password": password}).status_code == 200


def test_conversations_need_a_session(app, needs_db):
    with TestClient(app) as client:
        assert client.get("/api/v1/sessions").status_code == 401


def test_an_account_lists_opens_and_replays_its_conversation(app, needs_db):
    owner = new_owner()
    sid, answer = _seed(owner)
    with TestClient(app) as client:
        _login(client, owner.email, "owner-pass")

        listed = client.get("/api/v1/sessions").json()["sessions"]
        assert [(s["id"], s["title"], s["message_count"]) for s in listed] == [(sid, "Leaves", 2)]

        session = client.get(f"/api/v1/sessions/{sid}").json()
        assert [m["content"] for m in session["messages"]] == [
            "How do leaves make sugar?",
            "With light.",
        ]
        assert session["active_turns"] == []

        trace = client.get(f"/api/v1/sessions/{sid}/messages/{answer}/events").json()
        assert [e["type"] for e in trace["events"]] == ["content", "done"]

        found = client.get("/api/v1/sessions/search", params={"q": "sugar"}).json()
        assert found["total"] == 1


def test_another_account_gets_not_found(app, needs_db):
    owner = new_owner()
    sid, answer = _seed(owner)
    learner = new_learner(owner.group_id)
    with TestClient(app) as client:
        _login(client, learner.email, "learner-pass")
        assert client.get("/api/v1/sessions").json()["sessions"] == []
        assert client.get(f"/api/v1/sessions/{sid}").status_code == 404
        assert client.get(f"/api/v1/sessions/{sid}/messages/{answer}/events").status_code == 404
