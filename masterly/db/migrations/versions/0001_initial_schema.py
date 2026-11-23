"""Initial schema: the 14 tables of docs/design/co-so-du-lieu.md.

Revision ID: 0001
Revises:
Create Date: 2026-11-23
"""

from collections.abc import Sequence

from alembic import op
from pgvector.sqlalchemy import Vector
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table('groups',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('model_catalog', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('catalog_revision', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('codex_session', sa.LargeBinary(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_groups'))
    )
    op.create_table('accounts',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('group_id', sa.UUID(), nullable=False),
    sa.Column('role', sa.Text(), nullable=False),
    sa.Column('email', sa.Text(), nullable=False),
    sa.Column('password_hash', sa.Text(), nullable=False),
    sa.Column('display_name', sa.Text(), server_default='', nullable=False),
    sa.Column('avatar', sa.Text(), server_default='', nullable=False),
    sa.Column('theme', sa.Text(), server_default='light', nullable=False),
    sa.Column('language', sa.Text(), server_default='vi', nullable=False),
    sa.Column('disabled', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("language IN ('vi', 'en')", name=op.f('ck_accounts_language')),
    sa.CheckConstraint("role IN ('owner', 'learner')", name=op.f('ck_accounts_role')),
    sa.CheckConstraint("theme IN ('light', 'dark')", name=op.f('ck_accounts_theme')),
    sa.ForeignKeyConstraint(['group_id'], ['groups.id'], name=op.f('fk_accounts_group_id_groups'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_accounts'))
    )
    op.create_index(op.f('ix_accounts_group_id'), 'accounts', ['group_id'], unique=False)
    op.create_index('uq_accounts_email', 'accounts', [sa.literal_column('lower(email)')], unique=True)
    op.create_index('uq_accounts_group_owner', 'accounts', ['group_id'], unique=True, postgresql_where=sa.text("role = 'owner'"))
    op.create_table('memories',
    sa.Column('account_id', sa.UUID(), nullable=False),
    sa.Column('slot', sa.Text(), nullable=False),
    sa.Column('content', sa.Text(), server_default='', nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], name=op.f('fk_memories_account_id_accounts'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('account_id', 'slot', name=op.f('pk_memories'))
    )
    op.create_table('workspaces',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('account_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('is_default', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], name=op.f('fk_workspaces_account_id_accounts'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_workspaces'))
    )
    op.create_index(op.f('ix_workspaces_account_id'), 'workspaces', ['account_id'], unique=False)
    op.create_index('uq_workspaces_account_default', 'workspaces', ['account_id'], unique=True, postgresql_where=sa.text('is_default'))
    op.create_table('knowledge_bases',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('workspace_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('embedding_model', sa.Text(), server_default='', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_knowledge_bases_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_knowledge_bases'))
    )
    op.create_index(op.f('ix_knowledge_bases_workspace_id'), 'knowledge_bases', ['workspace_id'], unique=False)
    op.create_table('learning_paths',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('workspace_id', sa.UUID(), nullable=False),
    sa.Column('goal', sa.Text(), server_default='', nullable=False),
    sa.Column('status', sa.Text(), server_default='active', nullable=False),
    sa.Column('state', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('revision', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('active', 'archived')", name=op.f('ck_learning_paths_status')),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_learning_paths_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_learning_paths'))
    )
    op.create_index(op.f('ix_learning_paths_workspace_id'), 'learning_paths', ['workspace_id'], unique=False)
    op.create_table('documents',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('knowledge_base_id', sa.UUID(), nullable=False),
    sa.Column('folder', sa.Text(), server_default='', nullable=False),
    sa.Column('file_name', sa.Text(), nullable=False),
    sa.Column('storage_key', sa.Text(), nullable=False),
    sa.Column('size_bytes', sa.BigInteger(), nullable=False),
    sa.Column('status', sa.Text(), server_default='processing', nullable=False),
    sa.Column('error', sa.Text(), server_default='', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('processing', 'ready', 'failed')", name=op.f('ck_documents_status')),
    sa.ForeignKeyConstraint(['knowledge_base_id'], ['knowledge_bases.id'], name=op.f('fk_documents_knowledge_base_id_knowledge_bases'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_documents'))
    )
    op.create_index(op.f('ix_documents_knowledge_base_id'), 'documents', ['knowledge_base_id'], unique=False)
    op.create_table('sessions',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('workspace_id', sa.UUID(), nullable=False),
    sa.Column('path_id', sa.UUID(), nullable=True),
    sa.Column('title', sa.Text(), server_default='', nullable=False),
    sa.Column('summary', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('preferences', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['path_id'], ['learning_paths.id'], name=op.f('fk_sessions_path_id_learning_paths'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_sessions_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_sessions'))
    )
    op.create_index(op.f('ix_sessions_path_id'), 'sessions', ['path_id'], unique=False)
    op.create_index(op.f('ix_sessions_workspace_id'), 'sessions', ['workspace_id'], unique=False)
    op.create_table('assessments',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('path_id', sa.UUID(), nullable=False),
    sa.Column('knowledge_point_id', sa.Text(), nullable=False),
    sa.Column('session_id', sa.UUID(), nullable=True),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('result', sa.Text(), nullable=False),
    sa.Column('question', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('detail', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("kind IN ('quiz', 'qualitative', 'review')", name=op.f('ck_assessments_kind')),
    sa.CheckConstraint("result IN ('correct', 'incorrect', 'partial')", name=op.f('ck_assessments_result')),
    sa.ForeignKeyConstraint(['path_id'], ['learning_paths.id'], name=op.f('fk_assessments_path_id_learning_paths'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], name=op.f('fk_assessments_session_id_sessions'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_assessments'))
    )
    op.create_index('ix_assessments_path_point', 'assessments', ['path_id', 'knowledge_point_id', 'created_at'], unique=False)
    op.create_index(op.f('ix_assessments_session_id'), 'assessments', ['session_id'], unique=False)
    op.create_table('chunks',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('document_id', sa.UUID(), nullable=False),
    sa.Column('ordinal', sa.Integer(), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('locator', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('embedding', Vector(), nullable=True),
    sa.Column('search_text', postgresql.TSVECTOR(), sa.Computed("to_tsvector('simple', content)", persisted=True), nullable=True),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], name=op.f('fk_chunks_document_id_documents'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_chunks'))
    )
    op.create_index('ix_chunks_document_ordinal', 'chunks', ['document_id', 'ordinal'], unique=False)
    op.create_index('ix_chunks_search_text', 'chunks', ['search_text'], unique=False, postgresql_using='gin')
    op.create_table('messages',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('session_id', sa.UUID(), nullable=False),
    sa.Column('parent_id', sa.BigInteger(), nullable=True),
    sa.Column('role', sa.Text(), nullable=False),
    sa.Column('content', sa.Text(), server_default='', nullable=False),
    sa.Column('extra', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("role IN ('user', 'assistant')", name=op.f('ck_messages_role')),
    sa.ForeignKeyConstraint(['parent_id'], ['messages.id'], name=op.f('fk_messages_parent_id_messages'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], name=op.f('fk_messages_session_id_sessions'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_messages'))
    )
    op.create_index(op.f('ix_messages_parent_id'), 'messages', ['parent_id'], unique=False)
    op.create_index(op.f('ix_messages_session_id'), 'messages', ['session_id'], unique=False)
    op.create_table('notes',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('workspace_id', sa.UUID(), nullable=False),
    sa.Column('session_id', sa.UUID(), nullable=True),
    sa.Column('title', sa.Text(), server_default='', nullable=False),
    sa.Column('content', sa.Text(), server_default='', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], name=op.f('fk_notes_session_id_sessions'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_notes_workspace_id_workspaces'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_notes'))
    )
    op.create_index(op.f('ix_notes_session_id'), 'notes', ['session_id'], unique=False)
    op.create_index(op.f('ix_notes_workspace_id'), 'notes', ['workspace_id'], unique=False)
    op.create_table('turns',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('session_id', sa.UUID(), nullable=False),
    sa.Column('message_id', sa.BigInteger(), nullable=True),
    sa.Column('status', sa.Text(), server_default='running', nullable=False),
    sa.Column('error', sa.Text(), server_default='', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("status IN ('running', 'completed', 'failed', 'cancelled')", name=op.f('ck_turns_status')),
    sa.ForeignKeyConstraint(['message_id'], ['messages.id'], name=op.f('fk_turns_message_id_messages'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], name=op.f('fk_turns_session_id_sessions'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_turns'))
    )
    op.create_index(op.f('ix_turns_message_id'), 'turns', ['message_id'], unique=False)
    op.create_index(op.f('ix_turns_session_id'), 'turns', ['session_id'], unique=False)
    op.create_table('turn_events',
    sa.Column('turn_id', sa.UUID(), nullable=False),
    sa.Column('seq', sa.Integer(), nullable=False),
    sa.Column('type', sa.Text(), nullable=False),
    sa.Column('data', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['turn_id'], ['turns.id'], name=op.f('fk_turn_events_turn_id_turns'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('turn_id', 'seq', name=op.f('pk_turn_events'))
    )


def downgrade() -> None:
    op.drop_table("turn_events")
    op.drop_table("turns")
    op.drop_table("notes")
    op.drop_table("messages")
    op.drop_table("chunks")
    op.drop_table("assessments")
    op.drop_table("sessions")
    op.drop_table("documents")
    op.drop_table("learning_paths")
    op.drop_table("knowledge_bases")
    op.drop_table("workspaces")
    op.drop_table("memories")
    op.drop_table("accounts")
    op.drop_table("groups")
    op.execute("DROP EXTENSION IF EXISTS vector")
