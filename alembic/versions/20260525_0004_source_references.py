"""Create source_references table.

Revision ID: 20260525_0004
Revises: 20260525_0003
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260525_0004"
down_revision = "20260525_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the ``source_references`` table and indexes."""
    op.create_table(
        "source_references",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("stable_locator", sa.String(length=1024), nullable=False),
        sa.Column("passage_range", sa.String(length=120), nullable=True),
        sa.Column("content_hash", sa.String(length=128), nullable=False),
        sa.Column("hash_algorithm", sa.String(length=32), nullable=False),
        sa.Column("source_visibility", sa.String(length=32), nullable=False),
        sa.Column("drift_status", sa.String(length=32), nullable=False),
        sa.Column("multi_source_role", sa.String(length=32), nullable=True),
        sa.Column(
            "captured_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "source_type IN ('markdown-file', 'kindle-highlight', 'url', 'pdf-passage', 'internal-note')",
            name=op.f("ck_source_references_source_type_valid"),
        ),
        sa.CheckConstraint(
            "source_visibility IN ('public', 'local-only')",
            name=op.f("ck_source_references_source_visibility_valid"),
        ),
        sa.CheckConstraint(
            "drift_status IN ('current', 'stale', 'missing')",
            name=op.f("ck_source_references_drift_status_valid"),
        ),
        sa.CheckConstraint(
            "multi_source_role IS NULL OR multi_source_role IN ('primary', 'supporting', 'counterpoint')",
            name=op.f("ck_source_references_multi_source_role_valid"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source_references")),
    )
    op.create_index(op.f("ix_source_references_source_type"), "source_references", ["source_type"])
    op.create_index(
        op.f("ix_source_references_stable_locator"),
        "source_references",
        ["stable_locator"],
    )
    op.create_index(
        op.f("ix_source_references_content_hash"),
        "source_references",
        ["content_hash"],
    )
    op.create_index(
        op.f("ix_source_references_drift_status"),
        "source_references",
        ["drift_status"],
    )
    op.create_index(
        op.f("ix_source_references_captured_at"),
        "source_references",
        ["captured_at"],
    )


def downgrade() -> None:
    """Drop the ``source_references`` table and indexes."""
    op.drop_index(op.f("ix_source_references_captured_at"), table_name="source_references")
    op.drop_index(op.f("ix_source_references_drift_status"), table_name="source_references")
    op.drop_index(op.f("ix_source_references_content_hash"), table_name="source_references")
    op.drop_index(op.f("ix_source_references_stable_locator"), table_name="source_references")
    op.drop_index(op.f("ix_source_references_source_type"), table_name="source_references")
    op.drop_table("source_references")
