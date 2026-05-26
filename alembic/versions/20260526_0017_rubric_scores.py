"""Add rubric scores.

Revision ID: 20260526_0017_rubric_scores
Revises: 20260526_0016_rubrics
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260526_0017_rubric_scores"
down_revision = "20260526_0016_rubrics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create rubric score table."""
    op.create_table(
        "rubric_scores",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("rubric_id", sa.String(length=36), nullable=False),
        sa.Column("attempt_id", sa.String(length=36), nullable=False),
        sa.Column("learner_id", sa.String(length=36), nullable=False),
        sa.Column("scorer_type", sa.String(length=64), nullable=False),
        sa.Column("scorer_id", sa.String(length=255), nullable=True),
        sa.Column("scorer_version", sa.String(length=120), nullable=True),
        sa.Column("raw_score", sa.Float(), nullable=False),
        sa.Column("normalized_score", sa.Float(), nullable=False),
        sa.Column("max_score", sa.Float(), nullable=False),
        sa.Column("criterion_scores", sa.JSON(), nullable=False),
        sa.Column("evidence_record_id", sa.String(length=36), nullable=True),
        sa.Column("feedback_record_id", sa.String(length=36), nullable=True),
        sa.Column("score_metadata", sa.JSON(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "raw_score >= 0", name=op.f("ck_rubric_scores_rubric_score_raw_non_negative")
        ),
        sa.CheckConstraint(
            "max_score > 0", name=op.f("ck_rubric_scores_rubric_score_max_positive")
        ),
        sa.CheckConstraint(
            "normalized_score >= 0.0 AND normalized_score <= 1.0",
            name=op.f("ck_rubric_scores_rubric_score_normalized_unit_interval"),
        ),
        sa.ForeignKeyConstraint(["attempt_id"], ["attempts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["evidence_record_id"], ["evidence_records.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["feedback_record_id"], ["feedback_records.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["rubric_id"], ["rubrics.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "rubric_id",
        "attempt_id",
        "learner_id",
        "scorer_type",
        "normalized_score",
        "evidence_record_id",
        "feedback_record_id",
        "created_at",
    ):
        op.create_index(op.f(f"ix_rubric_scores_{column}"), "rubric_scores", [column])


def downgrade() -> None:
    """Drop rubric score table."""
    for column in (
        "created_at",
        "feedback_record_id",
        "evidence_record_id",
        "normalized_score",
        "scorer_type",
        "learner_id",
        "attempt_id",
        "rubric_id",
    ):
        op.drop_index(op.f(f"ix_rubric_scores_{column}"), table_name="rubric_scores")
    op.drop_table("rubric_scores")
