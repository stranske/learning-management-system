"""add maintenance items and grade disputes

The workplace knowledge-maintenance strand: source/entity-anchored retrieval
items that deliberately do NOT require a knowledge node or learning goal.

Revision ID: 20260803_0032
Revises: 20260802_0031
Create Date: 2026-08-03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260803_0032"
down_revision = "20260802_0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create maintenance_items and grade_disputes."""
    op.create_table(
        "maintenance_items",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "learner_id",
            sa.String(length=36),
            sa.ForeignKey("learners.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("item_type", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column(
            "source_reference_id",
            sa.String(length=36),
            sa.ForeignKey("source_references.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source_locator_hint", sa.String(length=300), nullable=True),
        sa.Column("subject_label", sa.String(length=200), nullable=True),
        sa.Column("retention_tier", sa.String(length=16), nullable=False, server_default="warm"),
        sa.Column("precision_mode", sa.String(length=16), nullable=False, server_default="band"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("relevant_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("content_as_of", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "item_type IN ('idea', 'reference_anchor')", name="maintenance_item_type_valid"
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'retired', 'superseded')",
            name="maintenance_item_status_valid",
        ),
        sa.CheckConstraint(
            "retention_tier IN ('hot', 'warm', 'cold')",
            name="maintenance_item_retention_tier_valid",
        ),
        sa.CheckConstraint(
            "precision_mode IN ('band', 'approximate', 'exact')",
            name="maintenance_item_precision_mode_valid",
        ),
    )
    op.create_index("ix_maintenance_items_learner_id", "maintenance_items", ["learner_id"])
    op.create_index("ix_maintenance_items_item_type", "maintenance_items", ["item_type"])
    op.create_index("ix_maintenance_items_status", "maintenance_items", ["status"])
    op.create_index("ix_maintenance_items_subject_label", "maintenance_items", ["subject_label"])
    op.create_index(
        "ix_maintenance_items_source_reference_id", "maintenance_items", ["source_reference_id"]
    )
    op.create_index("ix_maintenance_items_relevant_until", "maintenance_items", ["relevant_until"])
    op.create_index(
        "ix_maintenance_items_learner_status", "maintenance_items", ["learner_id", "status"]
    )

    op.create_table(
        "grade_disputes",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "learner_id",
            sa.String(length=36),
            sa.ForeignKey("learners.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "maintenance_item_id",
            sa.String(length=36),
            sa.ForeignKey("maintenance_items.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("evidence_record_id", sa.String(length=36), nullable=True),
        sa.Column("submitted_answer", sa.Text(), nullable=False),
        sa.Column("machine_grade", sa.Float(), nullable=True),
        sa.Column("learner_grade", sa.Float(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_grade_disputes_learner_id", "grade_disputes", ["learner_id"])
    op.create_index(
        "ix_grade_disputes_maintenance_item_id", "grade_disputes", ["maintenance_item_id"]
    )
    op.create_index(
        "ix_grade_disputes_evidence_record_id", "grade_disputes", ["evidence_record_id"]
    )


def downgrade() -> None:
    """Drop grade_disputes and maintenance_items."""
    op.drop_index("ix_grade_disputes_evidence_record_id", table_name="grade_disputes")
    op.drop_index("ix_grade_disputes_maintenance_item_id", table_name="grade_disputes")
    op.drop_index("ix_grade_disputes_learner_id", table_name="grade_disputes")
    op.drop_table("grade_disputes")
    for index in (
        "ix_maintenance_items_learner_status",
        "ix_maintenance_items_relevant_until",
        "ix_maintenance_items_source_reference_id",
        "ix_maintenance_items_subject_label",
        "ix_maintenance_items_status",
        "ix_maintenance_items_item_type",
        "ix_maintenance_items_learner_id",
    ):
        op.drop_index(index, table_name="maintenance_items")
    op.drop_table("maintenance_items")
