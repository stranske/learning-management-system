"""Add maintenance plans from gap analyses.

Revision ID: 20260526_0023_maintenance_plans
Revises: 20260526_0022_gap_analysis_scope_constraint_cleanup
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260526_0023_maintenance_plans"
down_revision = "20260526_0022_gap_analysis_scope_constraint_cleanup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create maintenance plan table."""
    op.create_table(
        "maintenance_plans",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("target_id", sa.String(length=36), nullable=False),
        sa.Column("gap_analysis_id", sa.String(length=36), nullable=False),
        sa.Column("learner_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="active", nullable=False),
        sa.Column("plan_steps", sa.JSON(), nullable=False),
        sa.Column("schedule_ids", sa.JSON(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column(
            "generated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("ownership_scope", sa.String(length=32), server_default="personal", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "ownership_scope = 'personal'",
            name=op.f("ck_maintenance_plans_personal_scope_only"),
        ),
        sa.CheckConstraint(
            "status IN ('active', 'completed', 'archived')",
            name=op.f("ck_maintenance_plans_status_valid"),
        ),
        sa.ForeignKeyConstraint(["target_id"], ["capability_targets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["gap_analysis_id"], ["gap_analyses.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["learner_id"], ["learners.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "target_id",
        "gap_analysis_id",
        "learner_id",
        "status",
        "generated_at",
        "ownership_scope",
    ):
        op.create_index(op.f(f"ix_maintenance_plans_{column}"), "maintenance_plans", [column])


def downgrade() -> None:
    """Drop maintenance plan table."""
    for column in (
        "ownership_scope",
        "generated_at",
        "status",
        "learner_id",
        "gap_analysis_id",
        "target_id",
    ):
        op.drop_index(op.f(f"ix_maintenance_plans_{column}"), table_name="maintenance_plans")
    op.drop_table("maintenance_plans")
