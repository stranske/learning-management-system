"""add learner review-budget settings

The owner's "ten minutes a day" is a heuristic that must be adjustable, and
the app derives collection capacity plus a sustainable intake rate from it.

Revision ID: 20260806_0035
Revises: 20260806_0034
Create Date: 2026-08-06
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260806_0035"
down_revision = "20260806_0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add per-learner budget columns with the documented defaults."""
    op.add_column(
        "learners",
        sa.Column("daily_minutes_target", sa.Integer(), nullable=False, server_default="10"),
    )
    op.add_column(
        "learners",
        sa.Column("daily_item_cap", sa.Integer(), nullable=False, server_default="25"),
    )


def downgrade() -> None:
    """Drop the budget columns."""
    with op.batch_alter_table("learners") as batch:
        batch.drop_column("daily_item_cap")
        batch.drop_column("daily_minutes_target")
