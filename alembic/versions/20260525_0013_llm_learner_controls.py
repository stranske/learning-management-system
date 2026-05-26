"""Add LLM learner controls and trace override state.

Revision ID: 20260525_0013_llm_learner_controls
Revises: 20260525_0012_llm_proposals
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260525_0013_llm_learner_controls"
down_revision = "20260525_0012_llm_proposals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Track coaching intensity and learner keep/forget trace controls."""
    with op.batch_alter_table("llm_sessions") as batch_op:
        batch_op.add_column(
            sa.Column(
                "coaching_intensity",
                sa.String(length=32),
                server_default="full",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "trace_control_state",
                sa.String(length=32),
                server_default="default",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column("transcript_deleted_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.create_check_constraint(
            op.f("ck_llm_sessions_coaching_intensity_valid"),
            "coaching_intensity IN ('full', 'light', 'quiet')",
        )
        batch_op.create_check_constraint(
            op.f("ck_llm_sessions_trace_control_state_valid"),
            "trace_control_state IN ('default', 'kept', 'forgotten')",
        )
    op.create_index(
        op.f("ix_llm_sessions_coaching_intensity"),
        "llm_sessions",
        ["coaching_intensity"],
    )
    op.create_index(
        op.f("ix_llm_sessions_trace_control_state"),
        "llm_sessions",
        ["trace_control_state"],
    )


def downgrade() -> None:
    """Remove LLM learner-control fields."""
    op.drop_index(op.f("ix_llm_sessions_trace_control_state"), table_name="llm_sessions")
    op.drop_index(op.f("ix_llm_sessions_coaching_intensity"), table_name="llm_sessions")
    with op.batch_alter_table("llm_sessions") as batch_op:
        batch_op.drop_constraint(
            op.f("ck_llm_sessions_trace_control_state_valid"),
            type_="check",
        )
        batch_op.drop_constraint(
            op.f("ck_llm_sessions_coaching_intensity_valid"),
            type_="check",
        )
        batch_op.drop_column("transcript_deleted_at")
        batch_op.drop_column("trace_control_state")
        batch_op.drop_column("coaching_intensity")
