"""add draft lifecycle fields and draft rejections

Drafted maintenance items are proposals: they carry an expiry, a record of
which payload fields came from the source versus were inferred, and an
approval timestamp. Rejections are kept after the item is discarded so the
reasons can condition future drafting.

Revision ID: 20260806_0034
Revises: 20260806_0033
Create Date: 2026-08-06
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260806_0034"
down_revision = "20260806_0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add draft lifecycle columns and the rejection log."""
    op.add_column(
        "maintenance_items",
        sa.Column("draft_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "maintenance_items", sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "maintenance_items",
        sa.Column("field_provenance", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.create_index(
        "ix_maintenance_items_draft_expires_at", "maintenance_items", ["draft_expires_at"]
    )
    # Items that already exist were created before approval was enforced;
    # mark the active ones approved so they are not retro-quarantined.
    op.execute(
        sa.text("UPDATE maintenance_items SET approved_at = created_at WHERE status = 'active'")
    )

    op.create_table(
        "draft_rejections",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "learner_id",
            sa.String(length=36),
            sa.ForeignKey("learners.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("item_type", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("subject_label", sa.String(length=200), nullable=True),
        sa.Column("source_locator_hint", sa.String(length=300), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("disposition", sa.String(length=16), nullable=False, server_default="rejected"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_draft_rejections_learner_id", "draft_rejections", ["learner_id"])
    op.create_index("ix_draft_rejections_disposition", "draft_rejections", ["disposition"])


def downgrade() -> None:
    """Drop the rejection log and the draft lifecycle columns."""
    op.drop_index("ix_draft_rejections_disposition", table_name="draft_rejections")
    op.drop_index("ix_draft_rejections_learner_id", table_name="draft_rejections")
    op.drop_table("draft_rejections")
    op.drop_index("ix_maintenance_items_draft_expires_at", table_name="maintenance_items")
    with op.batch_alter_table("maintenance_items") as batch:
        batch.drop_column("field_provenance")
        batch.drop_column("approved_at")
        batch.drop_column("draft_expires_at")
