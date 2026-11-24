"""The conversation store on PostgreSQL, scoped to one account."""

from __future__ import annotations

import asyncio

import pytest

from masterly.db.engine import dispose_engine
from masterly.services.session.store import ActiveTurnConflict, ChatStore
from tests.conftest import new_learner, new_owner


def run(work):
    """Run one async scenario on its own loop, with a fresh app engine."""

    async def main():
        try:
            return await work()
        finally:
            await dispose_engine()

    return asyncio.run(main())


@pytest.fixture
def store(needs_db) -> ChatStore:
    return ChatStore(new_owner().id)


def test_a_new_session_lands_in_the_default_workspace(store):
    async def work():
        session = await store.create_session()
        assert session["title"] == "New conversation"
        assert session["status"] == "idle"
        assert session["workspace_id"] == await store.default_workspace_id()
        listed = await store.list_sessions()
        assert [item["id"] for item in listed] == [session["id"]]
        assert listed[0]["message_count"] == 0

    run(work)


def test_another_account_cannot_reach_the_conversation(store):
    other = ChatStore(new_learner(new_owner().group_id).id)

    async def work():
        session = await store.create_session("Private")
        sid = session["id"]
        assert await other.get_session(sid) is None
        assert await other.list_sessions() == []
        assert await other.update_session_title(sid, "taken") is False
        assert await other.delete_session(sid) is False
        with pytest.raises(ValueError):
            await other.add_message(sid, "user", "hello")
        with pytest.raises(ValueError):
            await other.begin_turn(sid, "chat")
        assert await other.get_session("not-a-uuid") is None
        assert (await store.get_session(sid))["title"] == "Private"

    run(work)


def test_messages_chain_and_context_follows_one_branch(store):
    async def work():
        sid = (await store.create_session())["id"]
        first = await store.add_message(sid, "user", "Q1", capability="chat")
        answer = await store.add_message(sid, "assistant", "A1", metadata={"model": "m"})
        second = await store.add_message(sid, "user", "Q2")
        # An edit of Q2 starts a sibling branch under A1.
        edited = await store.add_message(sid, "user", "Q2 edited", parent_message_id=answer)

        messages = await store.get_messages(sid)
        assert [m["parent_message_id"] for m in messages] == [None, first, answer, answer]
        assert messages[0]["capability"] == "chat"
        assert messages[1]["metadata"] == {"model": "m"}

        branch = await store.get_messages_for_context(sid, leaf_message_id=edited)
        assert [m["content"] for m in branch] == ["Q1", "A1", "Q2 edited"]
        assert second not in [m["id"] for m in branch]
        assert (await store.get_last_message(sid, role="assistant"))["content"] == "A1"

    run(work)


def test_one_active_turn_per_session_and_finished_turns_stay_finished(store):
    async def work():
        sid = (await store.create_session())["id"]
        turn = await store.begin_turn(sid, "chat")
        assert turn["status"] == "running" and turn["capability"] == "chat"
        with pytest.raises(ActiveTurnConflict) as conflict:
            await store.begin_turn(sid, "chat")
        assert conflict.value.turn_id == turn["id"]

        assert await store.transition_turn(turn["id"], "waiting_input")
        assert (await store.get_session(sid))["active_turn_id"] == turn["id"]
        assert await store.transition_turn(turn["id"], "running", expected_status="completed") is False
        assert await store.transition_turn(
            turn["id"], "failed", error="boom", failure_code="provider", retryable=True
        )
        failed = await store.get_turn(turn["id"])
        assert failed["finished_at"] is not None
        assert (failed["failure_code"], failed["retryable"]) == ("provider", True)
        assert await store.transition_turn(turn["id"], "running") is False
        assert [t["id"] for t in await store.list_orphaned_failed_turns(sid)] == [turn["id"]]

        # The session is free again.
        assert (await store.begin_turn(sid, "chat"))["status"] == "running"

    run(work)


def test_events_replay_in_order_and_a_resent_event_must_match(store):
    async def work():
        sid = (await store.create_session())["id"]
        turn = await store.begin_turn(sid, "chat")
        stored = await store.append_events(
            turn["id"],
            [
                {"type": "stage_start", "stage": "responding"},
                {"type": "content", "content": "Hel"},
                {"type": "content", "content": "lo", "metadata": {"k": 1}},
            ],
        )
        assert [e["seq"] for e in stored] == [1, 2, 3]
        assert (await store.get_turn(turn["id"]))["last_seq"] == 3

        again = await store.append_events(
            turn["id"], [{"type": "content", "content": "lo", "metadata": {"k": 1}, "seq": 3}]
        )
        assert again[0]["timestamp"] == stored[2]["timestamp"]
        with pytest.raises(ValueError, match="conflict"):
            await store.append_events(turn["id"], [{"type": "content", "content": "x", "seq": 2}])

        after = await store.get_events(turn["id"], after_seq=1)
        assert [(e["seq"], e["content"]) for e in after] == [(2, "Hel"), (3, "lo")]
        assert after[1]["metadata"] == {"k": 1} and after[1]["session_id"] == sid

    run(work)


def test_an_answer_carries_a_preview_of_its_turn(store):
    async def work():
        sid = (await store.create_session())["id"]
        await store.add_message(sid, "user", "Why?")
        turn = await store.begin_turn(sid, "chat")
        await store.append_events(
            turn["id"],
            [
                {"type": "content", "content": "thinking"},
                {"type": "tool_call", "content": "web_search"},
                {"type": "progress", "metadata": {"ask_user": {"question": "Which?"}}},
                {"type": "done"},
            ],
        )
        answer = await store.add_message(sid, "assistant", "Because.")
        assert await store.link_turn_message(turn["id"], answer)
        assert await store.link_turn_message(turn["id"], answer) is False
        await store.transition_turn(turn["id"], "completed")

        messages = await store.get_messages(sid)
        assistant = messages[-1]
        assert [e["type"] for e in assistant["events"]] == ["tool_call", "progress", "done"]
        assert assistant["trace"]["total"] == 4 and assistant["trace"]["truncated"]

        context = await store.get_messages_for_context(sid)
        assert [e["type"] for e in context[-1]["events"]] == ["progress"]

        trace = await store.get_message_trace(sid, answer, after_seq=0, limit=2)
        assert [e["seq"] for e in trace["events"]] == [1, 2]
        assert (trace["complete"], trace["next_seq"], trace["last_seq"]) == (False, 2, 4)

    run(work)


def test_archive_restore_search_and_delete(store):
    async def work():
        kept = (await store.create_session("Photosynthesis"))["id"]
        await store.add_message(kept, "user", "How do leaves make sugar?")
        gone = (await store.create_session("Old"))["id"]

        assert await store.soft_delete_session(gone)
        assert [s["id"] for s in await store.list_sessions()] == [kept]
        assert [s["id"] for s in await store.list_deleted_sessions()] == [gone]
        assert await store.hard_delete_session(kept) is False  # not archived
        assert await store.restore_session(gone)

        found = await store.search_sessions("SUGAR")
        assert found["total"] == 1 and found["sessions"][0]["id"] == kept
        assert "sugar" in found["sessions"][0]["match_excerpt"].lower()

        await store.soft_delete_session(gone)
        assert await store.hard_delete_session(gone)
        assert await store.get_session(gone) is None

    run(work)


def test_preferences_merge_and_summary(store):
    async def work():
        sid = (await store.create_session())["id"]
        assert await store.update_session_preferences(sid, {"tools": ["web_search"]})
        assert await store.update_session_preferences(sid, {"language": "vi", "workspace_id": "x"})
        session = await store.get_session(sid)
        assert session["preferences"]["tools"] == ["web_search"]
        assert session["preferences"]["language"] == "vi"
        assert session["preferences"]["workspace_id"] == session["workspace_id"]

        assert await store.update_summary(sid, "earlier talk", 7)
        session = await store.get_session(sid)
        assert (session["compressed_summary"], session["summary_up_to_msg_id"]) == ("earlier talk", 7)

    run(work)


def test_deleting_a_question_takes_its_answer_and_turn(store):
    async def work():
        sid = (await store.create_session())["id"]
        q1 = await store.add_message(sid, "user", "Q1")
        a1 = await store.add_message(sid, "assistant", "A1")
        q2 = await store.add_message(sid, "user", "Q2", attachments=[{"id": "att-1"}])
        turn = await store.begin_turn(sid, "chat")
        a2 = await store.add_message(sid, "assistant", "A2")
        await store.link_turn_message(turn["id"], a2)

        running = await store.delete_turn_by_message(sid, q2)
        assert running["was_running"] and not running["deleted"]

        await store.transition_turn(turn["id"], "completed")
        q3 = await store.add_message(sid, "user", "Q3", parent_message_id=a2)
        result = await store.delete_turn_by_message(sid, q2)
        assert result["deleted"] and result["attachment_ids"] == ["att-1"]
        assert result["turn_id"] == turn["id"]
        assert await store.get_turn(turn["id"]) is None

        messages = await store.get_messages(sid)
        assert [m["id"] for m in messages] == [q1, a1, q3]
        assert messages[-1]["parent_message_id"] == a1

    run(work)
