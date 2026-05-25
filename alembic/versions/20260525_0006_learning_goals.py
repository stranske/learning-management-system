"""Create learning goal tables.

Revision ID: 20260525_0006
Revises: 20260525_0005
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260525_0006"
down_revision = "20260525_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create learner-owned goal records and target-node links."""
    op.create_table(
        "learning_goals",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("learner_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("knowledge_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="active", nullable=False),
        sa.Column("ownership_scope", sa.String(length=32), nullable=False),
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
        sa.CheckConstraint(
            "knowledge_type IN ('factual', 'conceptual', 'procedural', 'judgment', "
            "'metacognitive', 'social', 'compliance')",
            name=op.f("ck_learning_goals_knowledge_type_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('active', 'paused', 'completed', 'archived')",
            name=op.f("ck_learning_goals_status_valid"),
        ),
        sa.CheckConstraint(
            "ownership_scope IN ('personal', 'institutional')",
            name=op.f("ck_learning_goals_ownership_scope_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["learner_id"],
            ["learners.id"],
            name=op.f("fk_learning_goals_learner_id_learners"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_learning_goals")),
    )
    op.create_index(op.f("ix_learning_goals_learner_id"), "learning_goals", ["learner_id"])
    op.create_index(
        op.f("ix_learning_goals_knowledge_type"),
        "learning_goals",
        ["knowledge_type"],
    )
    op.create_index(op.f("ix_learning_goals_status"), "learning_goals", ["status"])
    op.create_index(
        op.f("ix_learning_goals_ownership_scope"),
        "learning_goals",
        ["ownership_scope"],
    )

    op.create_table(
        "learning_goal_nodes",
        sa.Column("learning_goal_id", sa.String(length=36), nullable=False),
        sa.Column("knowledge_node_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["learning_goal_id"],
            ["learning_goals.id"],
            name=op.f("fk_learning_goal_nodes_learning_goal_id_learning_goals"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["knowledge_node_id"],
            ["knowledge_nodes.id"],
            name=op.f("fk_learning_goal_nodes_knowledge_node_id_knowledge_nodes"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "learning_goal_id",
            "knowledge_node_id",
            name=op.f("pk_learning_goal_nodes"),
        ),
    )


def downgrade() -> None:
    """Drop learning goal tables and indexes."""
    op.drop_table("learning_goal_nodes")
    op.drop_index(op.f("ix_learning_goals_ownership_scope"), table_name="learning_goals")
    op.drop_index(op.f("ix_learning_goals_status"), table_name="learning_goals")
    op.drop_index(op.f("ix_learning_goals_knowledge_type"), table_name="learning_goals")
    op.drop_index(op.f("ix_learning_goals_learner_id"), table_name="learning_goals")
    op.drop_table("learning_goals")
