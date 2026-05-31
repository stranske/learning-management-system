"""Add learner reflection records (#204).

Revision ID: 20260531_0029_learner_reflections
Revises: 20260530_0028_user_password_hash
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260531_0029_learner_reflections"
down_revision = "20260530_0028_user_password_hash"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the learner reflection table used by the learner API."""
    op.create_table(
        "learner_reflections",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("learner_id", sa.String(length=36), nullable=False),
        sa.Column("knowledge_node_id", sa.String(length=36), nullable=True),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("response", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["knowledge_node_id"], ["knowledge_nodes.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["learner_id"], ["learners.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_learner_reflections_created_at"),
        "learner_reflections",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_learner_reflections_knowledge_node_id"),
        "learner_reflections",
        ["knowledge_node_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_learner_reflections_learner_id"),
        "learner_reflections",
        ["learner_id"],
        unique=False,
    )


def downgrade() -> None:
    """Drop learner reflection storage."""
    op.drop_index(op.f("ix_learner_reflections_learner_id"), table_name="learner_reflections")
    op.drop_index(
        op.f("ix_learner_reflections_knowledge_node_id"),
        table_name="learner_reflections",
    )
    op.drop_index(op.f("ix_learner_reflections_created_at"), table_name="learner_reflections")
    op.drop_table("learner_reflections")
