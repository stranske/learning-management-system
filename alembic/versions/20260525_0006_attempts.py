"""Create attempts table.

Revision ID: 20260525_0006_attempts
Revises: 20260525_0007
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260525_0006_attempts"
down_revision = "20260525_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create learner attempts with structured feedback."""
    op.create_table(
        "attempts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("learner_id", sa.String(length=36), nullable=False),
        sa.Column("prompt_id", sa.String(length=36), nullable=False),
        sa.Column("response_text", sa.Text(), nullable=False),
        sa.Column("response_metadata", sa.JSON(), nullable=True),
        sa.Column("confidence_rating", sa.Integer(), nullable=True),
        sa.Column("reference_accessed", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("hint_used", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("support_level", sa.String(length=32), server_default="none", nullable=False),
        sa.Column("elapsed_seconds", sa.Integer(), nullable=True),
        sa.Column("feedback", sa.JSON(), nullable=False),
        sa.Column("llm_session_id", sa.String(length=36), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "confidence_rating IS NULL OR (confidence_rating >= 1 AND confidence_rating <= 5)",
            name=op.f("ck_attempts_confidence_rating_valid"),
        ),
        sa.CheckConstraint(
            "support_level IN ('none', 'hint', 'reference', 'worked-example', 'coach')",
            name=op.f("ck_attempts_support_level_valid"),
        ),
        sa.CheckConstraint(
            "elapsed_seconds IS NULL OR elapsed_seconds >= 0",
            name=op.f("ck_attempts_elapsed_seconds_non_negative"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_attempts")),
    )
    op.create_index(op.f("ix_attempts_learner_id"), "attempts", ["learner_id"])
    op.create_index(op.f("ix_attempts_prompt_id"), "attempts", ["prompt_id"])
    op.create_index(op.f("ix_attempts_reference_accessed"), "attempts", ["reference_accessed"])
    op.create_index(op.f("ix_attempts_support_level"), "attempts", ["support_level"])
    op.create_index(op.f("ix_attempts_llm_session_id"), "attempts", ["llm_session_id"])
    op.create_index(op.f("ix_attempts_created_at"), "attempts", ["created_at"])


def downgrade() -> None:
    """Drop learner attempts."""
    op.drop_index(op.f("ix_attempts_created_at"), table_name="attempts")
    op.drop_index(op.f("ix_attempts_llm_session_id"), table_name="attempts")
    op.drop_index(op.f("ix_attempts_support_level"), table_name="attempts")
    op.drop_index(op.f("ix_attempts_reference_accessed"), table_name="attempts")
    op.drop_index(op.f("ix_attempts_prompt_id"), table_name="attempts")
    op.drop_index(op.f("ix_attempts_learner_id"), table_name="attempts")
    op.drop_table("attempts")
