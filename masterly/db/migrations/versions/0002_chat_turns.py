"""Chat turns: the states a turn passes through, its capability and failure.

A turn can wait in a queue or pause on a question to the learner, so ``status``
gains ``queued`` and ``waiting_input``. ``capability`` names what ran the turn
(the chat, later a learning path); ``failure_code`` and ``retryable`` say why a
turn failed and whether trying again can help. A session runs at most one turn
at a time, which the partial unique index enforces across processes.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-24
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ACTIVE = "status IN ('queued', 'running', 'waiting_input')"


def upgrade() -> None:
    op.drop_constraint(op.f("ck_turns_status"), "turns", type_="check")
    op.create_check_constraint(
        op.f("ck_turns_status"),
        "turns",
        "status IN ('queued', 'running', 'waiting_input', 'completed', 'failed', 'cancelled')",
    )
    op.add_column(
        "turns", sa.Column("capability", sa.Text(), server_default="", nullable=False)
    )
    op.add_column(
        "turns", sa.Column("failure_code", sa.Text(), server_default="", nullable=False)
    )
    op.add_column(
        "turns",
        sa.Column("retryable", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.create_index(
        "uq_turns_session_active",
        "turns",
        ["session_id"],
        unique=True,
        postgresql_where=sa.text(_ACTIVE),
    )


def downgrade() -> None:
    op.drop_index("uq_turns_session_active", table_name="turns")
    op.drop_column("turns", "retryable")
    op.drop_column("turns", "failure_code")
    op.drop_column("turns", "capability")
    op.drop_constraint(op.f("ck_turns_status"), "turns", type_="check")
    op.create_check_constraint(
        op.f("ck_turns_status"), "turns", "status IN ('running', 'completed', 'failed', 'cancelled')"
    )
