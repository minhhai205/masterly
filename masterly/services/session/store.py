"""Conversations on PostgreSQL: sessions, messages, turns and turn events.

One store per account. Every read and write is limited to sessions in that
account's workspaces, so one account can never reach another's conversation by
guessing an id.

The dictionaries returned keep the shape the chat runtime and the web client
already speak: string ids, epoch-second timestamps, and the per-message
``capability``/``events``/``attachments``/``metadata`` fields, which live
together in ``messages.extra``. A turn event's ``source``/``stage``/``content``/
``metadata``/``timestamp`` live in ``turn_events.data``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any
import uuid

from sqlalchemy import Select, and_, delete, exists, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from masterly.db import get_session_factory
from masterly.db.models import Message, Session, Turn, TurnEvent, Workspace

from .ask_user_trace import filter_ask_user_events
from .event_preview import MAX_TRACE_PREVIEW_EVENTS, compact_trace_preview
from .provider_response_state import redact_private_message_metadata
from .search import bounded_search_excerpt, normalize_search_query

ACTIVE_TURN_STATUSES = frozenset({"queued", "running", "waiting_input"})
TERMINAL_TURN_STATUSES = frozenset({"completed", "failed", "cancelled"})
ALL_TURN_STATUSES = ACTIVE_TURN_STATUSES | TERMINAL_TURN_STATUSES

DEFAULT_TITLE = "New conversation"
_TITLE_LIMIT = 100


class ActiveTurnConflict(RuntimeError):
    """A session already has a turn that has not finished.

    ``turn_id`` is the turn that blocks the session, when known.
    """

    def __init__(self, message: str, *, turn_id: str = "") -> None:
        super().__init__(message)
        self.turn_id = turn_id


class _Unset:
    pass


# ``add_message`` without a parent chains onto the latest message of the session.
_PARENT_AUTO = _Unset()


def _uuid(value: Any) -> uuid.UUID | None:
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


def _epoch(value: datetime | None) -> float | None:
    return value.timestamp() if value is not None else None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _title(value: str | None) -> str:
    return ((value or "").strip() or DEFAULT_TITLE)[:_TITLE_LIMIT]


def _trace_bounds(started_at: Any, ended_at: Any) -> dict[str, float]:
    """The turn's real wall-clock span, omitted when either end is unknown."""
    try:
        start = float(started_at)
        end = float(ended_at)
    except (TypeError, ValueError):
        return {}
    return {"started_at": start, "ended_at": max(start, end)}


def _card_present(path: str) -> str:
    return f"coalesce(data #> '{path}', 'null'::jsonb) <> 'null'::jsonb"


# Events that carry a card the learner answers (a clarifying question, a quiz
# question): a settled message cannot render without them.
_CARD_SQL = " OR ".join(
    _card_present(path)
    for path in (
        "{metadata,ask_user}",
        "{metadata,ask_user_resolved}",
        "{metadata,tool_metadata,ask_user}",
        "{metadata,mastery_question}",
        "{metadata,tool_metadata,mastery_question}",
    )
)
_ASK_USER_SQL = " OR ".join(
    _card_present(path)
    for path in (
        "{metadata,ask_user}",
        "{metadata,ask_user_resolved}",
        "{metadata,tool_metadata,ask_user}",
    )
)


class ChatStore:
    """The conversations of one account."""

    def __init__(self, account_id: str | uuid.UUID) -> None:
        resolved = _uuid(account_id)
        if resolved is None:
            raise ValueError(f"Not an account id: {account_id!r}")
        self.account_id = resolved

    # --- plumbing -----------------------------------------------------------

    @asynccontextmanager
    async def _db(self) -> AsyncIterator[AsyncSession]:
        async with get_session_factory()() as db, db.begin():
            yield db

    def _my_workspaces(self) -> Select:
        return select(Workspace.id).where(Workspace.account_id == self.account_id)

    def _owns_session(self, session_column: Any) -> Any:
        return session_column.in_(
            select(Session.id).where(Session.workspace_id.in_(self._my_workspaces()))
        )

    async def _session_id(self, db: AsyncSession, session_id: Any) -> uuid.UUID | None:
        sid = _uuid(session_id)
        if sid is None:
            return None
        return await db.scalar(
            select(Session.id).where(Session.id == sid, self._owns_session(Session.id))
        )

    async def _turn_row(
        self, db: AsyncSession, turn_id: Any, *, lock: bool = False
    ) -> Turn | None:
        tid = _uuid(turn_id)
        if tid is None:
            return None
        query = select(Turn).where(Turn.id == tid, self._owns_session(Turn.session_id))
        if lock:
            query = query.with_for_update()
        return await db.scalar(query)

    async def default_workspace_id(self) -> str:
        async with self._db() as db:
            workspace_id = await db.scalar(
                select(Workspace.id).where(
                    Workspace.account_id == self.account_id, Workspace.is_default
                )
            )
        if workspace_id is None:
            raise LookupError("This account has no default workspace")
        return str(workspace_id)

    # --- sessions -----------------------------------------------------------

    def _session_columns(self) -> list[Any]:
        latest = select(Turn).where(Turn.session_id == Session.id).order_by(
            Turn.created_at.desc()
        )
        active = (
            select(Turn.id)
            .where(Turn.session_id == Session.id, Turn.status.in_(ACTIVE_TURN_STATUSES))
            .limit(1)
            .scalar_subquery()
        )
        return [
            Session,
            func.coalesce(latest.with_only_columns(Turn.status).limit(1).scalar_subquery(), "idle")
            .label("status"),
            active.label("active_turn_id"),
            func.coalesce(
                latest.with_only_columns(Turn.capability).limit(1).scalar_subquery(), ""
            ).label("capability"),
        ]

    @staticmethod
    def _session_payload(row: Any) -> dict[str, Any]:
        session: Session = row[0]
        summary = session.summary or {}
        preferences = dict(session.preferences or {})
        preferences["workspace_id"] = str(session.workspace_id)
        payload = {
            "id": str(session.id),
            "session_id": str(session.id),
            "title": session.title or DEFAULT_TITLE,
            "workspace_id": str(session.workspace_id),
            "created_at": _epoch(session.created_at),
            "updated_at": _epoch(session.updated_at),
            "archived_at": _epoch(session.archived_at),
            "compressed_summary": summary.get("text", ""),
            "summary_up_to_msg_id": int(summary.get("up_to_message_id") or 0),
            "preferences": preferences,
            "status": row.status,
            "active_turn_id": str(row.active_turn_id) if row.active_turn_id else "",
            "capability": row.capability,
        }
        if "message_count" in row._fields:
            payload["message_count"] = int(row.message_count or 0)
            payload["last_message"] = row.last_message or ""
        return payload

    async def create_session(
        self,
        title: str | None = None,
        session_id: str | None = None,
        *,
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
        workspace = _uuid(workspace_id) if workspace_id else None
        async with self._db() as db:
            if workspace is None:
                workspace = await db.scalar(
                    select(Workspace.id).where(
                        Workspace.account_id == self.account_id, Workspace.is_default
                    )
                )
            elif not await db.scalar(
                select(exists().where(Workspace.id == workspace, Workspace.account_id == self.account_id))
            ):
                workspace = None
            if workspace is None:
                raise LookupError("No workspace of this account to hold the conversation")
            session = Session(workspace_id=workspace, title=_title(title))
            if session_id is not None:
                session.id = _uuid(session_id) or uuid.uuid4()
            db.add(session)
            await db.flush()
            sid = session.id
        created = await self.get_session(str(sid))
        assert created is not None
        return created

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        sid = _uuid(session_id)
        if sid is None:
            return None
        async with self._db() as db:
            row = (
                await db.execute(
                    select(*self._session_columns()).where(
                        Session.id == sid, self._owns_session(Session.id)
                    )
                )
            ).first()
        return self._session_payload(row) if row is not None else None

    async def ensure_session(self, session_id: str | None = None) -> dict[str, Any]:
        if session_id:
            session = await self.get_session(session_id)
            if session is not None:
                return session
        return await self.create_session()

    def _summary_query(self) -> Select:
        visible = and_(Message.session_id == Session.id, Message.content != "")
        return select(
            *self._session_columns(),
            select(func.count(Message.id))
            .where(Message.session_id == Session.id)
            .scalar_subquery()
            .label("message_count"),
            select(Message.content)
            .where(visible, func.trim(Message.content) != "")
            .order_by(Message.id.desc())
            .limit(1)
            .scalar_subquery()
            .label("last_message"),
        ).where(self._owns_session(Session.id))

    async def list_sessions(
        self,
        limit: int = 50,
        offset: int = 0,
        *,
        workspace_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Conversations not archived, newest activity first.

        Without ``workspace_id`` this lists the account's default workspace.
        """
        workspace = _uuid(workspace_id) if workspace_id else _uuid(await self.default_workspace_id())
        query = (
            self._summary_query()
            .where(Session.workspace_id == workspace, Session.archived_at.is_(None))
            .order_by(Session.updated_at.desc(), Session.id)
            .limit(limit)
            .offset(offset)
        )
        async with self._db() as db:
            rows = (await db.execute(query)).all()
        return [self._session_payload(row) for row in rows]

    async def list_deleted_sessions(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        """Archived conversations, most recently active first."""
        query = (
            self._summary_query()
            .where(Session.archived_at.is_not(None))
            .order_by(Session.updated_at.desc(), Session.id)
            .limit(limit)
            .offset(offset)
        )
        async with self._db() as db:
            rows = (await db.execute(query)).all()
        return [self._session_payload(row) for row in rows]

    async def get_session_summaries(self, session_ids: list[str]) -> list[dict[str, Any]]:
        ids = [sid for sid in (_uuid(item) for item in session_ids) if sid is not None]
        if not ids:
            return []
        async with self._db() as db:
            rows = (await db.execute(self._summary_query().where(Session.id.in_(ids)))).all()
        return [self._session_payload(row) for row in rows]

    async def search_sessions(
        self, query: str, limit: int = 50, offset: int = 0
    ) -> dict[str, Any]:
        """Conversations whose title or visible text contains ``query`` literally."""
        normalized = normalize_search_query(query)
        if not normalized:
            return {"sessions": [], "total": 0}
        needle = normalized.lower()
        in_title = func.strpos(func.lower(Session.title), needle) > 0
        in_message = exists().where(
            Message.session_id == Session.id, func.strpos(func.lower(Message.content), needle) > 0
        )
        matched = and_(Session.archived_at.is_(None), in_title | in_message)
        async with self._db() as db:
            total = await db.scalar(
                select(func.count(Session.id)).where(self._owns_session(Session.id), matched)
            )
            rows = (
                await db.execute(
                    self._summary_query()
                    .where(matched)
                    .order_by(Session.updated_at.desc(), Session.id)
                    .limit(max(1, min(int(limit), 100)))
                    .offset(max(0, int(offset)))
                )
            ).all()
            sessions = []
            for row in rows:
                payload = self._session_payload(row)
                match = await db.scalar(
                    select(Message.content)
                    .where(
                        Message.session_id == row[0].id,
                        func.strpos(func.lower(Message.content), needle) > 0,
                    )
                    .order_by(Message.id.desc())
                    .limit(1)
                )
                payload["match_excerpt"] = bounded_search_excerpt(
                    match or payload["title"], normalized
                )
                sessions.append(payload)
        return {"sessions": sessions, "total": int(total or 0)}

    async def _update_session(self, session_id: str, *conditions: Any, **values: Any) -> bool:
        sid = _uuid(session_id)
        if sid is None:
            return False
        async with self._db() as db:
            result = await db.execute(
                update(Session)
                .where(Session.id == sid, self._owns_session(Session.id), *conditions)
                .values(**values)
            )
        return result.rowcount > 0

    async def update_session_title(self, session_id: str, title: str) -> bool:
        return await self._update_session(session_id, title=_title(title), updated_at=_now())

    async def update_summary(self, session_id: str, summary: str, up_to_msg_id: int) -> bool:
        return await self._update_session(
            session_id,
            summary={"text": summary, "up_to_message_id": max(0, int(up_to_msg_id))},
            updated_at=Session.updated_at,
        )

    async def update_session_preferences(
        self, session_id: str, preferences: dict[str, Any]
    ) -> bool:
        """Merge ``preferences`` into the stored ones; the workspace is not one of them."""
        incoming = {k: v for k, v in (preferences or {}).items() if k != "workspace_id"}
        async with self._db() as db:
            sid = await self._session_id(db, session_id)
            if sid is None:
                return False
            session = await db.get(Session, sid, with_for_update=True)
            assert session is not None
            session.preferences = {**(session.preferences or {}), **incoming}
            session.updated_at = _now()
        return True

    async def soft_delete_session(self, session_id: str) -> bool:
        """Archive a conversation; ``restore_session`` brings it back."""
        return await self._update_session(
            session_id, Session.archived_at.is_(None), archived_at=_now()
        )

    async def restore_session(self, session_id: str) -> bool:
        return await self._update_session(
            session_id, Session.archived_at.is_not(None), archived_at=None
        )

    async def _delete_session(self, session_id: str, *conditions: Any) -> bool:
        sid = _uuid(session_id)
        if sid is None:
            return False
        async with self._db() as db:
            result = await db.execute(
                delete(Session).where(Session.id == sid, self._owns_session(Session.id), *conditions)
            )
        return result.rowcount > 0

    async def delete_session(self, session_id: str) -> bool:
        """Remove a conversation and everything in it, permanently."""
        return await self._delete_session(session_id)

    async def hard_delete_session(self, session_id: str) -> bool:
        """Permanently remove a conversation that is already archived."""
        return await self._delete_session(session_id, Session.archived_at.is_not(None))

    # --- turns --------------------------------------------------------------

    @staticmethod
    def _turn_payload(turn: Turn, last_seq: int = 0) -> dict[str, Any]:
        created = _epoch(turn.created_at)
        finished = _epoch(turn.finished_at)
        return {
            "id": str(turn.id),
            "turn_id": str(turn.id),
            "session_id": str(turn.session_id),
            "capability": turn.capability or "",
            "status": turn.status,
            "error": turn.error or "",
            "created_at": created,
            "updated_at": finished or created,
            "finished_at": finished,
            "last_seq": int(last_seq or 0),
            # Turns run in one process; these stay for callers that pass them.
            "owner_id": "",
            "fencing_token": 0,
            "state_version": 1,
            "failure_code": turn.failure_code or "",
            "retryable": bool(turn.retryable),
            "assistant_message_id": turn.message_id,
        }

    @staticmethod
    def _last_seq() -> Any:
        return (
            select(func.coalesce(func.max(TurnEvent.seq), 0))
            .where(TurnEvent.turn_id == Turn.id)
            .scalar_subquery()
            .label("last_seq")
        )

    async def begin_turn(
        self,
        session_id: str,
        capability: str = "",
        *,
        turn_id: str | None = None,
        owner_id: str = "",
        fencing_token: int = 0,
    ) -> dict[str, Any]:
        del owner_id, fencing_token  # single-process turns
        try:
            async with self._db() as db:
                sid = await self._session_id(db, session_id)
                if sid is None:
                    raise ValueError(f"Session not found: {session_id}")
                # Serialize the active-turn check per session.
                await db.execute(select(Session.id).where(Session.id == sid).with_for_update())
                active = await db.scalar(
                    select(Turn.id).where(
                        Turn.session_id == sid, Turn.status.in_(ACTIVE_TURN_STATUSES)
                    )
                )
                if active is not None:
                    raise ActiveTurnConflict(
                        f"Session already has an active turn: {active}", turn_id=str(active)
                    )
                turn = Turn(session_id=sid, capability=capability or "", status="running")
                if turn_id is not None:
                    turn.id = _uuid(turn_id) or uuid.uuid4()
                db.add(turn)
                await db.flush()
                await db.refresh(turn)
                return self._turn_payload(turn)
        except IntegrityError as exc:
            # The partial unique index wins a race the read above lost.
            raise ActiveTurnConflict(f"Session already has an active turn: {session_id}") from exc

    async def create_turn(self, session_id: str, capability: str = "") -> dict[str, Any]:
        return await self.begin_turn(session_id, capability)

    async def get_turn(self, turn_id: str) -> dict[str, Any] | None:
        tid = _uuid(turn_id)
        if tid is None:
            return None
        async with self._db() as db:
            row = (
                await db.execute(
                    select(Turn, self._last_seq()).where(
                        Turn.id == tid, self._owns_session(Turn.session_id)
                    )
                )
            ).first()
        return self._turn_payload(row[0], row.last_seq) if row is not None else None

    async def _list_turns(self, *conditions: Any) -> list[dict[str, Any]]:
        async with self._db() as db:
            rows = (
                await db.execute(
                    select(Turn, self._last_seq())
                    .where(self._owns_session(Turn.session_id), *conditions)
                    .order_by(Turn.created_at.desc())
                )
            ).all()
        return [self._turn_payload(row[0], row.last_seq) for row in rows]

    async def get_active_turn(self, session_id: str) -> dict[str, Any] | None:
        turns = await self.list_active_turns(session_id)
        return turns[0] if turns else None

    async def list_active_turns(self, session_id: str) -> list[dict[str, Any]]:
        sid = _uuid(session_id)
        if sid is None:
            return []
        return await self._list_turns(
            Turn.session_id == sid, Turn.status.in_(ACTIVE_TURN_STATUSES)
        )

    async def list_nonterminal_turns(self) -> list[dict[str, Any]]:
        turns = await self._list_turns(Turn.status.in_(ACTIVE_TURN_STATUSES))
        return list(reversed(turns))

    async def list_orphaned_failed_turns(self, session_id: str) -> list[dict[str, Any]]:
        """Failed turns that never produced an answer, oldest first."""
        sid = _uuid(session_id)
        if sid is None:
            return []
        turns = await self._list_turns(
            Turn.session_id == sid, Turn.status == "failed", Turn.message_id.is_(None)
        )
        return list(reversed(turns))

    async def transition_turn(
        self,
        turn_id: str,
        status: str,
        *,
        expected_status: str | None = None,
        fencing_token: int | None = None,
        error: str = "",
        failure_code: str = "",
        retryable: bool = False,
    ) -> bool:
        del fencing_token  # single-process turns
        if status not in ALL_TURN_STATUSES:
            raise ValueError(f"Unsupported turn status: {status}")
        async with self._db() as db:
            turn = await self._turn_row(db, turn_id, lock=True)
            if turn is None:
                return False
            if expected_status is not None and turn.status != expected_status:
                return False
            # A finished turn never changes state again.
            if turn.status in TERMINAL_TURN_STATUSES and turn.status != status:
                return False
            turn.status = status
            turn.error = error or ""
            turn.failure_code = failure_code or ""
            turn.retryable = bool(retryable)
            turn.finished_at = _now() if status in TERMINAL_TURN_STATUSES else None
        return True

    async def update_turn_status(self, turn_id: str, status: str, error: str = "") -> bool:
        return await self.transition_turn(turn_id, status, error=error)

    async def link_turn_message(self, turn_id: str, assistant_message_id: int | str) -> bool:
        """Point a turn at its answer, once, and only within the same session."""
        async with self._db() as db:
            turn = await self._turn_row(db, turn_id, lock=True)
            if turn is None or turn.message_id is not None:
                return False
            message_session = await db.scalar(
                select(Message.session_id).where(Message.id == int(assistant_message_id))
            )
            if message_session != turn.session_id:
                return False
            turn.message_id = int(assistant_message_id)
        return True

    # --- turn events --------------------------------------------------------

    @staticmethod
    def _event_payload(event: TurnEvent, session_id: str) -> dict[str, Any]:
        data = event.data or {}
        return {
            "type": event.type,
            "source": data.get("source", ""),
            "stage": data.get("stage", ""),
            "content": data.get("content", ""),
            "metadata": data.get("metadata", {}),
            "session_id": session_id,
            "turn_id": str(event.turn_id),
            "seq": event.seq,
            "timestamp": data.get("timestamp", _epoch(event.created_at)),
        }

    @staticmethod
    def _event_data(event: dict[str, Any], timestamp: float) -> dict[str, Any]:
        return {
            "source": str(event.get("source", "") or ""),
            "stage": str(event.get("stage", "") or ""),
            "content": str(event.get("content", "") or ""),
            "metadata": event.get("metadata") or {},
            "timestamp": timestamp,
        }

    async def append_events(
        self,
        turn_id: str,
        events: list[dict[str, Any]],
        *,
        fencing_token: int | None = None,
    ) -> list[dict[str, Any]]:
        """Store events in order; an event with a ``seq`` already stored must match it."""
        del fencing_token  # single-process turns
        now = _now()
        async with self._db() as db:
            turn = await self._turn_row(db, turn_id, lock=True)
            if turn is None:
                raise ValueError(f"Turn not found: {turn_id}")
            next_seq = (
                await db.scalar(
                    select(func.coalesce(func.max(TurnEvent.seq), 0)).where(
                        TurnEvent.turn_id == turn.id
                    )
                )
            ) + 1
            payloads: list[dict[str, Any]] = []
            for event in events:
                provided = int(event.get("seq") or 0)
                seq = provided if provided > 0 else next_seq
                next_seq = max(next_seq, seq + 1)
                payload = dict(event)
                payload["seq"] = seq
                payload["turn_id"] = payload.get("turn_id") or str(turn.id)
                payload["session_id"] = payload.get("session_id") or str(turn.session_id)
                existing = await db.get(TurnEvent, (turn.id, seq))
                if existing is not None:
                    stored = self._event_payload(existing, payload["session_id"])
                    same = all(
                        str(payload.get(key, "") or "") == str(stored[key] or "")
                        for key in ("type", "source", "stage", "content")
                    ) and (payload.get("metadata") or {}) == stored["metadata"]
                    if not same:
                        raise ValueError(f"Turn event conflict: {turn_id} seq={seq}")
                    payload["timestamp"] = stored["timestamp"]
                    payloads.append(payload)
                    continue
                timestamp = float(payload.get("timestamp") or now.timestamp())
                payload["timestamp"] = timestamp
                db.add(
                    TurnEvent(
                        turn_id=turn.id,
                        seq=seq,
                        type=str(payload.get("type", "") or ""),
                        data=self._event_data(payload, timestamp),
                    )
                )
                payloads.append(payload)
        return payloads

    async def append_turn_event(self, turn_id: str, event: dict[str, Any]) -> dict[str, Any]:
        return (await self.append_events(turn_id, [event]))[0]

    async def get_events(self, turn_id: str, after_seq: int = 0) -> list[dict[str, Any]]:
        async with self._db() as db:
            turn = await self._turn_row(db, turn_id)
            if turn is None:
                return []
            rows = (
                await db.scalars(
                    select(TurnEvent)
                    .where(TurnEvent.turn_id == turn.id, TurnEvent.seq > max(0, int(after_seq)))
                    .order_by(TurnEvent.seq)
                )
            ).all()
        return [self._event_payload(row, str(turn.session_id)) for row in rows]

    async def get_turn_events(self, turn_id: str, after_seq: int = 0) -> list[dict[str, Any]]:
        return await self.get_events(turn_id, after_seq)

    async def get_message_trace(
        self,
        session_id: str,
        message_id: int | str,
        after_seq: int = 0,
        limit: int | None = None,
    ) -> dict[str, Any] | None:
        """One page of the events behind an answer, for expanding its steps."""
        try:
            mid = int(message_id)
        except (TypeError, ValueError):
            return None
        row_limit = 500 if limit is None else min(1000, max(1, int(limit)))
        async with self._db() as db:
            sid = await self._session_id(db, session_id)
            if sid is None:
                return None
            if not await db.scalar(
                select(exists().where(Message.id == mid, Message.session_id == sid))
            ):
                return None
            turn_id = await db.scalar(select(Turn.id).where(Turn.message_id == mid))
            if turn_id is None:
                return {
                    "session_id": str(sid),
                    "message_id": mid,
                    "turn_id": None,
                    "events": [],
                    "total": 0,
                    "last_seq": 0,
                    "next_seq": None,
                    "complete": True,
                }
            total, last_seq = (
                await db.execute(
                    select(func.count(), func.coalesce(func.max(TurnEvent.seq), 0)).where(
                        TurnEvent.turn_id == turn_id
                    )
                )
            ).one()
            rows = (
                await db.scalars(
                    select(TurnEvent)
                    .where(TurnEvent.turn_id == turn_id, TurnEvent.seq > max(0, int(after_seq)))
                    .order_by(TurnEvent.seq)
                    .limit(row_limit)
                )
            ).all()
        events = [self._event_payload(row, str(sid)) for row in rows]
        last_loaded = events[-1]["seq"] if events else int(after_seq)
        complete = last_loaded >= int(last_seq)
        return {
            "session_id": str(sid),
            "message_id": mid,
            "turn_id": str(turn_id),
            "events": events,
            "total": int(total),
            "last_seq": int(last_seq),
            "next_seq": None if complete else last_loaded,
            "complete": complete,
        }

    # --- messages -----------------------------------------------------------

    @staticmethod
    def _message_payload(
        message: Message,
        events: list[dict[str, Any]] | None = None,
        trace: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        extra = message.extra or {}
        return {
            "id": message.id,
            "session_id": str(message.session_id),
            "role": message.role,
            "content": message.content or "",
            "capability": extra.get("capability", ""),
            "events": extra.get("events", []) if events is None else events,
            "attachments": extra.get("attachments", []),
            "metadata": extra.get("metadata", {}),
            "created_at": _epoch(message.created_at),
            "parent_message_id": message.parent_id,
            **({"trace": trace} if trace is not None else {}),
        }

    async def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        capability: str = "",
        events: list[dict[str, Any]] | None = None,
        attachments: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
        parent_message_id: int | str | None | _Unset = _PARENT_AUTO,
    ) -> int:
        """Append a message; without a parent it follows the latest one.

        An explicit ``None`` parent starts at the root of the conversation, as
        editing its very first message does.
        """
        async with self._db() as db:
            sid = await self._session_id(db, session_id)
            if sid is None:
                raise ValueError(f"Session not found: {session_id}")
            if isinstance(parent_message_id, _Unset):
                parent = await db.scalar(
                    select(Message.id)
                    .where(Message.session_id == sid)
                    .order_by(Message.id.desc())
                    .limit(1)
                )
            else:
                parent = int(parent_message_id) if parent_message_id is not None else None
            message = Message(
                session_id=sid,
                parent_id=parent,
                role=role,
                content=content or "",
                extra={
                    "capability": capability or "",
                    "events": events or [],
                    "attachments": attachments or [],
                    "metadata": metadata or {},
                },
            )
            db.add(message)
            await db.execute(update(Session).where(Session.id == sid).values(updated_at=_now()))
            await db.flush()
            return int(message.id)

    async def _message_query(self, session_id: str, *conditions: Any) -> list[Message]:
        async with self._db() as db:
            sid = await self._session_id(db, session_id)
            if sid is None:
                return []
            return list(
                (
                    await db.scalars(
                        select(Message)
                        .where(Message.session_id == sid, *conditions)
                        .order_by(Message.id)
                    )
                ).all()
            )

    async def get_last_message(
        self, session_id: str, role: str | None = None
    ) -> dict[str, Any] | None:
        conditions = [Message.role == role] if role else []
        messages = await self._message_query(session_id, *conditions)
        return self._message_payload(messages[-1]) if messages else None

    async def delete_message(self, message_id: int | str) -> bool:
        async with self._db() as db:
            result = await db.execute(
                delete(Message).where(
                    Message.id == int(message_id), self._owns_session(Message.session_id)
                )
            )
        return result.rowcount > 0

    async def _trace_preview(
        self, db: AsyncSession, turn_id: uuid.UUID, session_id: str
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """The bounded slice of a turn's events a settled message shows.

        Terminal and card events are always kept; tool activity fills the
        rest. The full trace is a separate, paged read.
        """
        stats = (
            await db.execute(
                text(
                    "SELECT count(*) AS total, coalesce(max(seq), 0) AS last_seq,"
                    " min((data->>'timestamp')::float) AS started_at,"
                    " max((data->>'timestamp')::float) AS ended_at"
                    " FROM turn_events WHERE turn_id = :turn_id"
                ),
                {"turn_id": turn_id},
            )
        ).one()
        by_seq: dict[int, TurnEvent] = {}
        for condition in (
            f"type IN ('done', 'error', 'cancelled', 'result') OR {_CARD_SQL}",
            "type IN ('done', 'error', 'cancelled', 'result', 'tool_call', 'tool_result')"
            f" OR {_CARD_SQL}",
        ):
            rows = (
                await db.scalars(
                    select(TurnEvent)
                    .where(TurnEvent.turn_id == turn_id, text(f"({condition})"))
                    .order_by(TurnEvent.seq.desc())
                    .limit(MAX_TRACE_PREVIEW_EVENTS)
                )
            ).all()
            by_seq.update({row.seq: row for row in rows})
        events = [self._event_payload(by_seq[seq], session_id) for seq in sorted(by_seq)]
        preview, compacted = compact_trace_preview(events)
        total = int(stats.total)
        return preview, {
            "turn_id": str(turn_id),
            "total": total,
            "last_seq": int(stats.last_seq),
            "truncated": compacted or total != len(preview),
            **_trace_bounds(stats.started_at, stats.ended_at),
        }

    async def get_messages(self, session_id: str) -> list[dict[str, Any]]:
        async with self._db() as db:
            sid = await self._session_id(db, session_id)
            if sid is None:
                return []
            rows = (
                await db.execute(
                    select(Message, Turn.id)
                    .outerjoin(Turn, Turn.message_id == Message.id)
                    .where(Message.session_id == sid)
                    .order_by(Message.id)
                )
            ).all()
            result = []
            for message, turn_id in rows:
                if message.role == "assistant" and turn_id is not None:
                    events, trace = await self._trace_preview(db, turn_id, str(sid))
                    result.append(self._message_payload(message, events=events, trace=trace))
                else:
                    result.append(self._message_payload(message))
        return result

    async def _ask_user_events(
        self, db: AsyncSession, turn_id: uuid.UUID, session_id: str
    ) -> list[dict[str, Any]]:
        rows = (
            await db.scalars(
                select(TurnEvent)
                .where(TurnEvent.turn_id == turn_id, text(f"({_ASK_USER_SQL})"))
                .order_by(TurnEvent.seq.desc())
                .limit(MAX_TRACE_PREVIEW_EVENTS)
            )
        ).all()
        return [self._event_payload(row, session_id) for row in reversed(rows)]

    async def get_messages_for_context(
        self, session_id: str, leaf_message_id: int | None = None
    ) -> list[dict[str, Any]]:
        """The messages a turn sends the model, oldest first.

        With ``leaf_message_id`` only that message and its ancestors count, so
        a re-run after an edit never sees the abandoned branch. Each message
        carries its clarifying-question events, which the model needs to read
        the learner's answers in context.
        """
        async with self._db() as db:
            sid = await self._session_id(db, session_id)
            if sid is None:
                return []
            rows = (
                await db.execute(
                    select(Message, Turn.id)
                    .outerjoin(Turn, Turn.message_id == Message.id)
                    .where(Message.session_id == sid)
                    .order_by(Message.id)
                )
            ).all()
            by_id = {message.id: (message, turn_id) for message, turn_id in rows}
            if leaf_message_id is None:
                chain = list(by_id.values())
            else:
                chain = []
                current: int | None = int(leaf_message_id)
                seen: set[int] = set()
                while current is not None and current in by_id and current not in seen:
                    seen.add(current)
                    chain.append(by_id[current])
                    current = by_id[current][0].parent_id
                chain.reverse()
            result = []
            for message, turn_id in chain:
                extra = message.extra or {}
                events = (
                    await self._ask_user_events(db, turn_id, str(sid))
                    if turn_id is not None
                    else filter_ask_user_events(extra.get("events", []))
                )
                result.append(
                    {
                        "id": message.id,
                        "role": message.role,
                        "content": message.content or "",
                        "events": events,
                        "metadata": extra.get("metadata", {}),
                    }
                )
        return result

    async def delete_turn_by_message(self, session_id: str, message_id: int) -> dict[str, Any]:
        """Delete a question with its answer (either one named) and their turn.

        Refused while that turn is still running. Messages that followed the
        pair are re-attached to the pair's parent.
        """
        nothing = {"deleted": False, "attachment_ids": [], "turn_id": None, "was_running": False}
        async with self._db() as db:
            sid = await self._session_id(db, session_id)
            if sid is None:
                return nothing
            message = await db.scalar(
                select(Message).where(Message.id == int(message_id), Message.session_id == sid)
            )
            if message is None:
                return nothing
            if message.role == "user":
                paired = await db.scalar(
                    select(Message)
                    .where(
                        Message.session_id == sid,
                        Message.role == "assistant",
                        Message.id > message.id,
                    )
                    .order_by(Message.id)
                    .limit(1)
                )
            else:
                paired = await db.scalar(
                    select(Message)
                    .where(Message.session_id == sid, Message.role == "user", Message.id < message.id)
                    .order_by(Message.id.desc())
                    .limit(1)
                )
            question = message if message.role == "user" else paired
            turn = None
            if question is not None:
                turn = await db.scalar(
                    select(Turn)
                    .where(Turn.session_id == sid, Turn.created_at >= question.created_at)
                    .order_by(Turn.created_at)
                    .limit(1)
                )
            if turn is not None and turn.status in ACTIVE_TURN_STATUSES:
                return {**nothing, "turn_id": str(turn.id), "was_running": True}

            pair = [m for m in (message, paired) if m is not None]
            attachment_ids = [
                attachment.get("id") or attachment.get("attachment_id")
                for m in pair
                for attachment in (m.extra or {}).get("attachments", [])
                if attachment.get("id") or attachment.get("attachment_id")
            ]
            if turn is not None:
                await db.delete(turn)
            for doomed in sorted(pair, key=lambda m: m.id, reverse=True):
                await db.execute(
                    update(Message)
                    .where(Message.session_id == sid, Message.parent_id == doomed.id)
                    .values(parent_id=doomed.parent_id)
                )
            ids = [m.id for m in pair]
            await db.execute(delete(Message).where(Message.id.in_(ids)))
            session = await db.get(Session, sid)
            assert session is not None
            summary = session.summary or {}
            if any(mid <= int(summary.get("up_to_message_id") or 0) for mid in ids):
                session.summary = {**summary, "up_to_message_id": 0}
            session.updated_at = _now()
        return {
            "deleted": True,
            "attachment_ids": attachment_ids,
            "turn_id": str(turn.id) if turn is not None else None,
            "was_running": False,
        }

    async def get_session_with_messages(self, session_id: str) -> dict[str, Any] | None:
        session = await self.get_session(session_id)
        if session is None:
            return None
        session["messages"] = await self.get_messages(session_id)
        redact_private_message_metadata(session["messages"])
        session["active_turns"] = await self.list_active_turns(session_id)
        return session


def get_session_store() -> ChatStore:
    """The conversations of the signed-in account."""
    from masterly.multi_user.context import get_current_user

    return ChatStore(get_current_user().id)


__all__ = [
    "ACTIVE_TURN_STATUSES",
    "ALL_TURN_STATUSES",
    "ActiveTurnConflict",
    "ChatStore",
    "DEFAULT_TITLE",
    "TERMINAL_TURN_STATUSES",
    "get_session_store",
]
