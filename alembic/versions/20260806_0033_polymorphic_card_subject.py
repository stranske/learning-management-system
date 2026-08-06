"""generalize review card state to a polymorphic subject

FSRS memory state was keyed to ``knowledge_node_id``, but the maintenance
strand schedules source-anchored items that deliberately have no
``KnowledgeNode``. Replacing the column with ``subject_type`` +
``subject_id`` lets one scheduler serve both families.

Existing rows are all concept-map nodes, so the backfill is a straight copy.

Revision ID: 20260806_0033
Revises: 20260803_0032
Create Date: 2026-08-06
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260806_0033"
down_revision = "20260803_0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the polymorphic subject columns and backfill from knowledge_node_id."""
    op.add_column(
        "review_card_states",
        sa.Column(
            "subject_type", sa.String(length=32), nullable=False, server_default="knowledge_node"
        ),
    )
    op.add_column(
        "review_card_states", sa.Column("subject_id", sa.String(length=36), nullable=True)
    )
    # Every pre-existing card is a knowledge node.
    op.execute(
        sa.text(
            "UPDATE review_card_states "
            "SET subject_id = knowledge_node_id, subject_type = 'knowledge_node' "
            "WHERE subject_id IS NULL"
        )
    )

    op.drop_index("ux_review_card_states_learner_node", table_name="review_card_states")
    op.drop_index("ix_review_card_states_knowledge_node_id", table_name="review_card_states")
    with op.batch_alter_table("review_card_states") as batch:
        batch.alter_column("subject_id", existing_type=sa.String(length=36), nullable=False)
        batch.drop_column("knowledge_node_id")
        batch.create_check_constraint(
            "review_card_subject_type_valid",
            "subject_type IN ('knowledge_node', 'maintenance_item')",
        )

    op.create_index(
        "ux_review_card_states_learner_subject",
        "review_card_states",
        ["learner_id", "subject_type", "subject_id"],
        unique=True,
    )
    op.create_index("ix_review_card_states_subject_id", "review_card_states", ["subject_id"])
    op.create_index("ix_review_card_states_subject_type", "review_card_states", ["subject_type"])


def downgrade() -> None:
    """Restore the knowledge-node-only shape, dropping maintenance-item cards."""
    op.drop_index("ix_review_card_states_subject_type", table_name="review_card_states")
    op.drop_index("ix_review_card_states_subject_id", table_name="review_card_states")
    op.drop_index("ux_review_card_states_learner_subject", table_name="review_card_states")

    # Maintenance-item cards have no knowledge node to map back to.
    op.execute(sa.text("DELETE FROM review_card_states WHERE subject_type <> 'knowledge_node'"))
    op.add_column(
        "review_card_states", sa.Column("knowledge_node_id", sa.String(length=36), nullable=True)
    )
    op.execute(sa.text("UPDATE review_card_states SET knowledge_node_id = subject_id"))
    with op.batch_alter_table("review_card_states") as batch:
        batch.alter_column("knowledge_node_id", existing_type=sa.String(length=36), nullable=False)
        batch.drop_constraint("review_card_subject_type_valid", type_="check")
        batch.drop_column("subject_id")
        batch.drop_column("subject_type")

    op.create_index(
        "ix_review_card_states_knowledge_node_id", "review_card_states", ["knowledge_node_id"]
    )
    op.create_index(
        "ux_review_card_states_learner_node",
        "review_card_states",
        ["learner_id", "knowledge_node_id"],
        unique=True,
    )
