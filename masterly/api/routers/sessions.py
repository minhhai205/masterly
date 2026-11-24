"""Conversations of the signed-in account: list, search, open, and replay steps.

Every route reads through the account's own store, so an id from another
account answers 404 exactly like an id that never existed.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from masterly.services.session.provider_response_state import (
    redact_private_message_metadata as _redact_provider_state_metadata,
)
from masterly.services.session.search import MAX_SEARCH_QUERY_CHARS
from masterly.services.session.store import get_session_store

router = APIRouter()

MAX_EVENT_PAYLOAD = 1024 * 1024
_TRUNCATION_NOTICE = "\n\n[... content truncated]"
_TRUNCATABLE_EVENT_TYPES = ("tool_result", "observation")


def _redact_private_message_metadata(messages: list[dict[str, Any]]) -> None:
    """Remove provider-only state before session details cross the API."""
    _redact_provider_state_metadata(messages)


def _attach_orphaned_failed_turns(
    messages: list[dict[str, Any]], turns: list[dict[str, Any]]
) -> None:
    """Expose a failed turn beside its saved user row when no reply exists.

    A question without a turn id falls back to the first one written during the
    turn is the safe fallback. A failed preflight with no saved user row is
    deliberately omitted rather than attached to an unrelated question.
    """
    users = [
        (index, message) for index, message in enumerate(messages) if message.get("role") == "user"
    ]
    for turn in turns:
        turn_id = str(turn.get("turn_id") or turn.get("id") or "")
        started = float(turn.get("created_at") or 0)
        finished = float(turn.get("finished_at") or turn.get("updated_at") or 0)
        match = next(
            (
                (index, message)
                for index, message in users
                if str((message.get("metadata") or {}).get("turn_id") or "") == turn_id
            ),
            None,
        )
        if match is None:
            match = next(
                (
                    (index, message)
                    for index, message in users
                    if started <= float(message.get("created_at") or 0) <= finished
                ),
                None,
            )
        if match is None:
            continue
        _, user = match
        # A later retry may have answered this same question. Its real answer
        # wins; showing the earlier failure beside it would tell the learner
        # that the answered question is still broken.
        if any(
            message.get("role") == "assistant"
            and str(message.get("parent_message_id") or "") == str(user.get("id") or "")
            and float(message.get("created_at") or 0) >= started
            for message in messages
        ):
            continue
        metadata = user.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
            user["metadata"] = metadata
        previous = metadata.get("orphaned_failed_turn")
        if isinstance(previous, dict) and float(previous.get("finished_at") or 0) > finished:
            continue
        metadata["orphaned_failed_turn"] = {
            "turn_id": turn_id,
            "error": str(turn.get("error") or ""),
            "failure_code": str(turn.get("failure_code") or ""),
            "retryable": bool(turn.get("retryable")),
            "finished_at": finished,
        }


def _truncate_oversized_events(
    messages: list[dict[str, Any]], limit: int = MAX_EVENT_PAYLOAD
) -> None:
    """Cap oversized ``tool_result``/``observation`` payloads in place.

    The store returns each message's events as a parsed list, so this edits
    that list directly. Only what the page renders is affected.
    """

    def _cap(container: dict[str, Any], field: str) -> bool:
        value = container.get(field)
        if isinstance(value, str) and len(value) > limit:
            container[field] = value[:limit] + _TRUNCATION_NOTICE
            return True
        return False

    for msg in messages:
        events = msg.get("events")
        if not isinstance(events, list):
            continue
        for event in events:
            if not isinstance(event, dict) or event.get("type") not in _TRUNCATABLE_EVENT_TYPES:
                continue
            truncated = _cap(event, "content")
            tool_metadata = (event.get("metadata") or {}).get("tool_metadata")
            if isinstance(tool_metadata, dict):
                for field in ("content", "answer"):
                    truncated = _cap(tool_metadata, field) or truncated
            if truncated:
                event["_truncated"] = True


@router.get("")
async def list_sessions(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    workspace_id: str | None = Query(default=None),
):
    """Conversations of a workspace (the default one when not given), newest first."""
    sessions = await get_session_store().list_sessions(
        limit=limit, offset=offset, workspace_id=workspace_id
    )
    return {"sessions": sessions}


@router.get("/search")
async def search_sessions(
    q: str = Query(..., min_length=1, max_length=MAX_SEARCH_QUERY_CHARS),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    return await get_session_store().search_sessions(q, limit=limit, offset=offset)


@router.get("/{session_id}")
async def get_session(session_id: str):
    store = get_session_store()
    session = await store.get_session_with_messages(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    _attach_orphaned_failed_turns(
        session.get("messages", []), await store.list_orphaned_failed_turns(session_id)
    )
    _redact_private_message_metadata(session.get("messages", []))
    _truncate_oversized_events(session.get("messages", []))
    return session


@router.get("/{session_id}/messages/{message_id}/events")
async def get_message_events(
    session_id: str,
    message_id: str,
    after_seq: int = Query(default=0, ge=0),
    limit: int = Query(default=500, ge=1, le=1000),
):
    trace = await get_session_store().get_message_trace(session_id, message_id, after_seq, limit)
    if trace is None:
        raise HTTPException(status_code=404, detail="Message not found")
    return trace
