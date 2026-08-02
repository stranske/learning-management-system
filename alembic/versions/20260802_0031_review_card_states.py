"""add FSRS review card states

Per-learner, per-node memory state (stability, difficulty, due) plus a
retention tier, replacing the implicit "count prior successes" memory of the
v1 interval ladder.

Revision ID: 20260802_0031
Revises: 20260617_0030
Create Date: 2026-08-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260802_0031"
down_revision = "20260617_0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the review_card_states table."""
    op.create_table(
        "review_card_states",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "learner_id",
            sa.String(length=36),
            sa.ForeignKey("learners.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("knowledge_node_id", sa.String(length=36), nullable=False),
        sa.Column(
            "retention_tier",
            sa.String(length=16),
            nullable=False,
            server_default="warm",
        ),
        sa.Column("card_state", sa.JSON(), nullable=False),
        sa.Column("stability", sa.Float(), nullable=True),
        sa.Column("difficulty", sa.Float(), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_review_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lapse_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "seeded_from_legacy_ladder",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "retention_tier IN ('hot', 'warm', 'cold')",
            name="review_card_retention_tier_valid",
        ),
    )
    op.create_index(
        "ux_review_card_states_learner_node",
        "review_card_states",
        ["learner_id", "knowledge_node_id"],
        unique=True,
    )
    op.create_index(
        "ix_review_card_states_due",
        "review_card_states",
        ["learner_id", "due_at"],
    )
    op.create_index(
        "ix_review_card_states_learner_id",
        "review_card_states",
        ["learner_id"],
    )
    op.create_index(
        "ix_review_card_states_knowledge_node_id",
        "review_card_states",
        ["knowledge_node_id"],
    )
    op.create_index(
        "ix_review_card_states_due_at",
        "review_card_states",
        ["due_at"],
    )


def downgrade() -> None:
    """Drop the review_card_states table."""
    op.drop_index("ix_review_card_states_due_at", table_name="review_card_states")
    op.drop_index("ix_review_card_states_knowledge_node_id", table_name="review_card_states")
    op.drop_index("ix_review_card_states_learner_id", table_name="review_card_states")
    op.drop_index("ix_review_card_states_due", table_name="review_card_states")
    op.drop_index("ux_review_card_states_learner_node", table_name="review_card_states")
    op.drop_table("review_card_states")
