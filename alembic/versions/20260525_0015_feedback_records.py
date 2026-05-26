"""Add durable feedback records and actions.

Revision ID: 20260525_0015_feedback_records
Revises: 20260525_0014_scheduler_records
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260525_0015_feedback_records"
down_revision = "20260525_0014_scheduler_records"
branch_labels = None
depends_on = None

FEEDBACK_LEVELS = ("affirmation", "coaching", "remediation", "review")
FEEDBACK_ACTION_TYPES = (
    "retry",
    "parallel-prompt",
    "prerequisite-remediation",
    "model-comparison",
    "revision",
    "coach-review",
    "author-review",
)
FEEDBACK_ACTION_STATUSES = ("open", "in-progress", "completed", "dismissed")


def _sql_values(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    """Create feedback record and action tables."""
    op.create_table(
        "feedback_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("learner_id", sa.String(length=36), nullable=False),
        sa.Column("attempt_id", sa.String(length=36), nullable=True),
        sa.Column("prompt_id", sa.String(length=36), nullable=True),
        sa.Column("evidence_record_id", sa.String(length=36), nullable=True),
        sa.Column("feedback_level", sa.String(length=32), server_default="coaching", nullable=False),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("observed_evidence", sa.Text(), nullable=False),
        sa.Column("diagnosis", sa.Text(), nullable=True),
        sa.Column("gap", sa.Text(), nullable=True),
        sa.Column("source_feedback", sa.JSON(), nullable=False),
        sa.Column("next_action_ids", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            f"feedback_level IN ({_sql_values(FEEDBACK_LEVELS)})",
            name=op.f("ck_feedback_records_feedback_record_level_valid"),
        ),
        sa.ForeignKeyConstraint(["attempt_id"], ["attempts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["evidence_record_id"], ["evidence_records.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "learner_id",
        "attempt_id",
        "prompt_id",
        "evidence_record_id",
        "feedback_level",
        "created_at",
    ):
        op.create_index(op.f(f"ix_feedback_records_{column}"), "feedback_records", [column])

    op.create_table(
        "feedback_actions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("feedback_record_id", sa.String(length=36), nullable=True),
        sa.Column("learner_id", sa.String(length=36), nullable=False),
        sa.Column("attempt_id", sa.String(length=36), nullable=True),
        sa.Column("prompt_id", sa.String(length=36), nullable=True),
        sa.Column("action_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="open", nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("action_metadata", sa.JSON(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            f"action_type IN ({_sql_values(FEEDBACK_ACTION_TYPES)})",
            name=op.f("ck_feedback_actions_feedback_action_type_valid"),
        ),
        sa.CheckConstraint(
            f"status IN ({_sql_values(FEEDBACK_ACTION_STATUSES)})",
            name=op.f("ck_feedback_actions_feedback_action_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["feedback_record_id"], ["feedback_records.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "feedback_record_id",
        "learner_id",
        "attempt_id",
        "prompt_id",
        "action_type",
        "status",
        "due_at",
        "created_at",
    ):
        op.create_index(op.f(f"ix_feedback_actions_{column}"), "feedback_actions", [column])


def downgrade() -> None:
    """Drop feedback action and record tables."""
    for column in (
        "created_at",
        "due_at",
        "status",
        "action_type",
        "prompt_id",
        "attempt_id",
        "learner_id",
        "feedback_record_id",
    ):
        op.drop_index(op.f(f"ix_feedback_actions_{column}"), table_name="feedback_actions")
    op.drop_table("feedback_actions")

    for column in (
        "created_at",
        "feedback_level",
        "evidence_record_id",
        "prompt_id",
        "attempt_id",
        "learner_id",
    ):
        op.drop_index(op.f(f"ix_feedback_records_{column}"), table_name="feedback_records")
    op.drop_table("feedback_records")
