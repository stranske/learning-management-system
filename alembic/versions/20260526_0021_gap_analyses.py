"""Add personal capability gap analyses.

Revision ID: 20260526_0021_gap_analyses
Revises: 20260526_0020_transfer_cases
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260526_0021_gap_analyses"
down_revision = "20260526_0020_transfer_cases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create gap analysis table."""
    op.create_table(
        "gap_analyses",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("target_id", sa.String(length=36), nullable=False),
        sa.Column("estimate_id", sa.String(length=36), nullable=False),
        sa.Column("learner_id", sa.String(length=36), nullable=False),
        sa.Column(
            "generated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("gap_items", sa.JSON(), nullable=False),
        sa.Column("severity", sa.String(length=32), server_default="low", nullable=False),
        sa.Column("required_evidence", sa.JSON(), nullable=False),
        sa.Column("recommended_action_types", sa.JSON(), nullable=False),
        sa.Column("ownership_scope", sa.String(length=32), server_default="personal", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "ownership_scope IN ('personal', 'institutional')",
            name=op.f("ck_gap_analyses_ownership_scope_valid"),
        ),
        sa.CheckConstraint(
            "ownership_scope = 'personal'",
            name=op.f("ck_gap_analyses_personal_scope_only"),
        ),
        sa.CheckConstraint(
            "severity IN ('low', 'medium', 'high')",
            name=op.f("ck_gap_analyses_severity_valid"),
        ),
        sa.ForeignKeyConstraint(["target_id"], ["capability_targets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["estimate_id"], ["capability_estimates.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["learner_id"], ["learners.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "target_id",
        "estimate_id",
        "learner_id",
        "generated_at",
        "severity",
        "ownership_scope",
    ):
        op.create_index(op.f(f"ix_gap_analyses_{column}"), "gap_analyses", [column])


def downgrade() -> None:
    """Drop gap analysis table."""
    for column in (
        "ownership_scope",
        "severity",
        "generated_at",
        "learner_id",
        "estimate_id",
        "target_id",
    ):
        op.drop_index(op.f(f"ix_gap_analyses_{column}"), table_name="gap_analyses")
    op.drop_table("gap_analyses")
