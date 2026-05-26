"""Add personal capability estimates.

Revision ID: 20260526_0020_capability_estimates
Revises: 20260526_0019_capability_targets
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260526_0020_capability_estimates"
down_revision = "20260526_0019_capability_targets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create capability estimate table."""
    op.create_table(
        "capability_estimates",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("target_id", sa.String(length=36), nullable=False),
        sa.Column("learner_id", sa.String(length=36), nullable=False),
        sa.Column(
            "generated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("estimator_version", sa.String(length=120), nullable=False),
        sa.Column("current_score", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("validity_scope", sa.Text(), nullable=False),
        sa.Column("evidence_breakdown", sa.JSON(), nullable=False),
        sa.Column("weak_node_ids", sa.JSON(), nullable=False),
        sa.Column("commentary", sa.Text(), nullable=False),
        sa.Column(
            "commentary_redaction_class",
            sa.String(length=64),
            server_default="learner-facing-inferred-mastery",
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "current_score >= 0.0 AND current_score <= 1.0",
            name=op.f("ck_capability_estimates_current_score_unit_interval"),
        ),
        sa.CheckConstraint(
            "confidence >= 0.0 AND confidence <= 1.0",
            name=op.f("ck_capability_estimates_confidence_unit_interval"),
        ),
        sa.CheckConstraint(
            "commentary_redaction_class IN "
            "('learner-facing-inferred-mastery', 'internal-inferred-mastery')",
            name=op.f("ck_capability_estimates_commentary_redaction_class_valid"),
        ),
        sa.ForeignKeyConstraint(["target_id"], ["capability_targets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["learner_id"], ["learners.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "target_id",
        "learner_id",
        "generated_at",
        "commentary_redaction_class",
    ):
        op.create_index(op.f(f"ix_capability_estimates_{column}"), "capability_estimates", [column])


def downgrade() -> None:
    """Drop capability estimate table."""
    for column in (
        "commentary_redaction_class",
        "generated_at",
        "learner_id",
        "target_id",
    ):
        op.drop_index(op.f(f"ix_capability_estimates_{column}"), table_name="capability_estimates")
    op.drop_table("capability_estimates")
