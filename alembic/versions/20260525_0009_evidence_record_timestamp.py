"""Add explicit timestamp to evidence records.

Revision ID: 20260525_0009_evidence_record_timestamp
Revises: 20260525_0008_evidence_records
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260525_0009_evidence_record_timestamp"
down_revision = "20260525_0008_evidence_records"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add explicit mastery timestamp field for evidence records."""
    op.add_column(
        "evidence_records",
        sa.Column(
            "timestamp", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(op.f("ix_evidence_records_timestamp"), "evidence_records", ["timestamp"])


def downgrade() -> None:
    """Drop explicit mastery timestamp field."""
    op.drop_index(op.f("ix_evidence_records_timestamp"), table_name="evidence_records")
    op.drop_column("evidence_records", "timestamp")
