"""Add revision request loops.

Revision ID: 20260526_0026_revision_requests
Revises: 20260526_0025_hints_model_answers
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260526_0026_revision_requests"
down_revision = "20260526_0025_hints_model_answers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the revision_requests table for request-to-revised-submission loops."""
    op.create_table(
        "revision_requests",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("learner_id", sa.String(length=36), nullable=False),
        sa.Column("feedback_record_id", sa.String(length=36), nullable=True),
        sa.Column("feedback_action_id", sa.String(length=36), nullable=True),
        sa.Column("prompt_id", sa.String(length=36), nullable=True),
        sa.Column("original_attempt_id", sa.String(length=36), nullable=True),
        sa.Column("revised_attempt_id", sa.String(length=36), nullable=True),
        sa.Column("work_product_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=32), server_default="open", nullable=False),
        sa.Column("result_note", sa.Text(), nullable=True),
        sa.Column("scheduler_hook", sa.JSON(), nullable=True),
        sa.Column(
            "requested_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('open', 'submitted', 'accepted', 'closed', 'superseded')",
            name=op.f("ck_revision_requests_revision_request_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["feedback_record_id"], ["feedback_records.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["feedback_action_id"], ["feedback_actions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["original_attempt_id"], ["attempts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["revised_attempt_id"], ["attempts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "learner_id",
        "feedback_record_id",
        "feedback_action_id",
        "prompt_id",
        "original_attempt_id",
        "revised_attempt_id",
        "work_product_id",
        "status",
        "requested_at",
        "created_at",
    ):
        op.create_index(op.f(f"ix_revision_requests_{column}"), "revision_requests", [column])


def downgrade() -> None:
    """Drop the revision_requests table."""
    for column in (
        "created_at",
        "requested_at",
        "status",
        "work_product_id",
        "revised_attempt_id",
        "original_attempt_id",
        "prompt_id",
        "feedback_action_id",
        "feedback_record_id",
        "learner_id",
    ):
        op.drop_index(op.f(f"ix_revision_requests_{column}"), table_name="revision_requests")
    op.drop_table("revision_requests")
