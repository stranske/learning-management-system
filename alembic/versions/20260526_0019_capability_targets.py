"""Add personal capability targets.

Revision ID: 20260526_0019_capability_targets
Revises: 20260526_0018_competencies
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260526_0019_capability_targets"
down_revision = "20260526_0018_competencies"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create capability target tables."""
    op.create_table(
        "capability_targets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("learner_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "ownership_scope", sa.String(length=32), server_default="personal", nullable=False
        ),
        sa.Column("learning_goal_id", sa.String(length=36), nullable=True),
        sa.Column("required_evidence_types", sa.JSON(), nullable=False),
        sa.Column("confidence_threshold", sa.Float(), server_default="0.8", nullable=False),
        sa.Column("status", sa.String(length=32), server_default="active", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "ownership_scope IN ('personal', 'institutional')",
            name=op.f("ck_capability_targets_ownership_scope_valid"),
        ),
        sa.CheckConstraint(
            "ownership_scope = 'personal'",
            name=op.f("ck_capability_targets_personal_scope_only"),
        ),
        sa.CheckConstraint(
            "confidence_threshold >= 0.0 AND confidence_threshold <= 1.0",
            name=op.f("ck_capability_targets_confidence_threshold_unit_interval"),
        ),
        sa.CheckConstraint(
            "status IN ('active', 'archived')",
            name=op.f("ck_capability_targets_status_valid"),
        ),
        sa.ForeignKeyConstraint(["learner_id"], ["learners.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["learning_goal_id"], ["learning_goals.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "learner_id",
        "title",
        "ownership_scope",
        "learning_goal_id",
        "status",
        "created_at",
    ):
        op.create_index(op.f(f"ix_capability_targets_{column}"), "capability_targets", [column])

    op.create_table(
        "capability_target_nodes",
        sa.Column("capability_target_id", sa.String(length=36), nullable=False),
        sa.Column("knowledge_node_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["capability_target_id"], ["capability_targets.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["knowledge_node_id"], ["knowledge_nodes.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("capability_target_id", "knowledge_node_id"),
    )
    op.create_table(
        "capability_target_competencies",
        sa.Column("capability_target_id", sa.String(length=36), nullable=False),
        sa.Column("competency_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["capability_target_id"], ["capability_targets.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["competency_id"], ["competencies.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("capability_target_id", "competency_id"),
    )


def downgrade() -> None:
    """Drop capability target tables."""
    op.drop_table("capability_target_competencies")
    op.drop_table("capability_target_nodes")
    for column in (
        "created_at",
        "status",
        "learning_goal_id",
        "ownership_scope",
        "title",
        "learner_id",
    ):
        op.drop_index(op.f(f"ix_capability_targets_{column}"), table_name="capability_targets")
    op.drop_table("capability_targets")
