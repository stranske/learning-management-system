"""Create review queue items table.

Revision ID: 20260525_0011_review_queue_items
Revises: 20260525_0010_llm_sessions
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260525_0011_review_queue_items"
down_revision = "20260525_0010_llm_sessions"
branch_labels = None
depends_on = None

REASON_CODES = (
    "new-learning",
    "due-review",
    "overdue",
    "remediation",
    "stale",
    "blocked-prerequisite",
)
QUEUE_STATUSES = ("pending", "dispatched", "completed", "skipped")


def _values(values: tuple[str, ...]) -> str:
    """Render a SQL ``IN`` clause body from string literals."""
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    """Create the review_queue_items table."""
    op.create_table(
        "review_queue_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("learner_id", sa.String(length=36), nullable=False),
        sa.Column("knowledge_node_id", sa.String(length=36), nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=False),
        sa.Column("reason_explanation", sa.Text(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("priority", sa.Float(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("source_attempt_id", sa.String(length=36), nullable=True),
        sa.Column("source_evidence_record_id", sa.String(length=36), nullable=True),
        sa.Column("decision_log", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_review_queue_items"),
        sa.ForeignKeyConstraint(
            ["source_attempt_id"],
            ["attempts.id"],
            name="fk_review_queue_items_source_attempt_id_attempts",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_evidence_record_id"],
            ["evidence_records.id"],
            name="fk_review_queue_items_source_evidence_record_id",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            f"reason_code IN ({_values(REASON_CODES)})",
            name="ck_review_queue_items_reason_code_valid",
        ),
        sa.CheckConstraint(
            f"status IN ({_values(QUEUE_STATUSES)})",
            name="ck_review_queue_items_status_valid",
        ),
        sa.CheckConstraint(
            "priority >= 0.0 AND priority <= 1.0",
            name="ck_review_queue_items_priority_unit_interval",
        ),
    )
    op.create_index(
        "ix_review_queue_items_learner_id",
        "review_queue_items",
        ["learner_id"],
    )
    op.create_index(
        "ix_review_queue_items_knowledge_node_id",
        "review_queue_items",
        ["knowledge_node_id"],
    )
    op.create_index(
        "ix_review_queue_items_reason_code",
        "review_queue_items",
        ["reason_code"],
    )
    op.create_index(
        "ix_review_queue_items_due_at",
        "review_queue_items",
        ["due_at"],
    )
    op.create_index(
        "ix_review_queue_items_status",
        "review_queue_items",
        ["status"],
    )
    op.create_index(
        "ix_review_queue_items_source_attempt_id",
        "review_queue_items",
        ["source_attempt_id"],
    )
    op.create_index(
        "ix_review_queue_items_source_evidence_record_id",
        "review_queue_items",
        ["source_evidence_record_id"],
    )
    op.create_index(
        "ix_review_queue_items_created_at",
        "review_queue_items",
        ["created_at"],
    )


def downgrade() -> None:
    """Drop the review_queue_items table."""
    op.drop_index("ix_review_queue_items_created_at", table_name="review_queue_items")
    op.drop_index(
        "ix_review_queue_items_source_evidence_record_id",
        table_name="review_queue_items",
    )
    op.drop_index("ix_review_queue_items_source_attempt_id", table_name="review_queue_items")
    op.drop_index("ix_review_queue_items_status", table_name="review_queue_items")
    op.drop_index("ix_review_queue_items_due_at", table_name="review_queue_items")
    op.drop_index("ix_review_queue_items_reason_code", table_name="review_queue_items")
    op.drop_index("ix_review_queue_items_knowledge_node_id", table_name="review_queue_items")
    op.drop_index("ix_review_queue_items_learner_id", table_name="review_queue_items")
    op.drop_table("review_queue_items")
