"""Enforce one active review_policies row per identity tuple.

Revision ID: 20260526_0015_review_policy_active_unique
Revises: 20260525_0014_scheduler_records
"""

from __future__ import annotations

from alembic import op

revision = "20260526_0015_review_policy_active_unique"
down_revision = "20260525_0014_scheduler_records"
branch_labels = None
depends_on = None


_INDEX_NAME = "uq_review_policies_active_identity"


def upgrade() -> None:
    """Add a partial unique index protecting active policy identity."""
    op.execute(
        f"CREATE UNIQUE INDEX IF NOT EXISTS {_INDEX_NAME} "
        "ON review_policies ("
        "reason_code, policy_version, "
        "COALESCE(knowledge_type, ''), COALESCE(ownership_scope, '')"
        ") WHERE is_active"
    )


def downgrade() -> None:
    """Drop the partial unique index."""
    op.execute(f"DROP INDEX IF EXISTS {_INDEX_NAME}")
