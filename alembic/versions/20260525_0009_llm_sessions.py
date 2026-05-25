"""Create llm_sessions table.

Revision ID: 20260525_0009_llm_sessions
Revises: 20260525_0006_attempts
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260525_0009_llm_sessions"
down_revision = "20260525_0006_attempts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the llm_sessions table with trace-class and accounting columns."""
    op.create_table(
        "llm_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("trace_class", sa.String(length=32), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("prompt_template_version", sa.String(length=120), nullable=True),
        sa.Column("learner_id", sa.String(length=36), nullable=True),
        sa.Column("parent_session_id", sa.String(length=36), nullable=True),
        sa.Column("input_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("output_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cost_micro_usd", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "redaction_applied",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column(
            "redacted_span_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "external_export_allowed",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
        sa.Column("response_summary", sa.Text(), nullable=True),
        sa.Column("is_replay", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "trace_class IN ('evidence-grade', 'formative', 'ephemeral')",
            name=op.f("ck_llm_sessions_trace_class_valid"),
        ),
        sa.CheckConstraint(
            "mode IN ('study-coach', 'practice', 'transfer', 'authoring-assist')",
            name=op.f("ck_llm_sessions_mode_valid"),
        ),
        sa.CheckConstraint(
            "input_tokens >= 0 AND output_tokens >= 0 AND cost_micro_usd >= 0",
            name=op.f("ck_llm_sessions_accounting_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["parent_session_id"],
            ["llm_sessions.id"],
            name=op.f("fk_llm_sessions_parent_session_id_llm_sessions"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_llm_sessions")),
    )
    op.create_index(op.f("ix_llm_sessions_mode"), "llm_sessions", ["mode"])
    op.create_index(op.f("ix_llm_sessions_trace_class"), "llm_sessions", ["trace_class"])
    op.create_index(op.f("ix_llm_sessions_learner_id"), "llm_sessions", ["learner_id"])


def downgrade() -> None:
    """Drop the llm_sessions table."""
    op.drop_index(op.f("ix_llm_sessions_learner_id"), table_name="llm_sessions")
    op.drop_index(op.f("ix_llm_sessions_trace_class"), table_name="llm_sessions")
    op.drop_index(op.f("ix_llm_sessions_mode"), table_name="llm_sessions")
    op.drop_table("llm_sessions")
