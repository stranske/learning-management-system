"""Store immutable prompt-version source hashes and drift acknowledgements.

Revision ID: 20261117_0038
Revises: 20261117_0037
Create Date: 2026-11-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261117_0038"
down_revision = "20261117_0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add snapshot and acknowledgement tables without backfilling legacy versions."""
    op.create_table(
        "prompt_version_source_snapshots",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("prompt_version_id", sa.String(length=36), nullable=False),
        sa.Column("source_reference_id", sa.String(length=36), nullable=False),
        sa.Column("content_hash", sa.String(length=128), nullable=False),
        sa.Column("hash_algorithm", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["prompt_version_id"],
            ["prompt_versions.id"],
            name=op.f("fk_prompt_version_source_snapshots_prompt_version_id"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_reference_id"],
            ["source_references.id"],
            name=op.f("fk_prompt_version_source_snapshots_source_reference_id"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_prompt_version_source_snapshots")),
        sa.UniqueConstraint(
            "prompt_version_id",
            "source_reference_id",
            name=op.f("uq_prompt_version_source_snapshots_prompt_version_id"),
        ),
    )
    op.create_index(
        op.f("ix_prompt_version_source_snapshots_prompt_version_id"),
        "prompt_version_source_snapshots",
        ["prompt_version_id"],
    )
    op.create_index(
        op.f("ix_prompt_version_source_snapshots_source_reference_id"),
        "prompt_version_source_snapshots",
        ["source_reference_id"],
    )

    op.create_table(
        "prompt_drift_acknowledgements",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("prompt_id", sa.String(length=36), nullable=False),
        sa.Column("prompt_version_id", sa.String(length=36), nullable=False),
        sa.Column("acknowledged_by", sa.String(length=255), nullable=False),
        sa.Column(
            "acknowledged_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["prompt_id"],
            ["prompts.id"],
            name=op.f("fk_prompt_drift_acknowledgements_prompt_id"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["prompt_version_id"],
            ["prompt_versions.id"],
            name=op.f("fk_prompt_drift_acknowledgements_prompt_version_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_prompt_drift_acknowledgements")),
        sa.UniqueConstraint(
            "prompt_id",
            "prompt_version_id",
            name=op.f("uq_prompt_drift_acknowledgements_prompt_id"),
        ),
    )
    op.create_index(
        op.f("ix_prompt_drift_acknowledgements_prompt_id"),
        "prompt_drift_acknowledgements",
        ["prompt_id"],
    )
    op.create_index(
        op.f("ix_prompt_drift_acknowledgements_prompt_version_id"),
        "prompt_drift_acknowledgements",
        ["prompt_version_id"],
    )


def downgrade() -> None:
    """Drop prompt drift acknowledgement and snapshot tables."""
    op.drop_index(
        op.f("ix_prompt_drift_acknowledgements_prompt_version_id"),
        table_name="prompt_drift_acknowledgements",
    )
    op.drop_index(
        op.f("ix_prompt_drift_acknowledgements_prompt_id"),
        table_name="prompt_drift_acknowledgements",
    )
    op.drop_table("prompt_drift_acknowledgements")
    op.drop_index(
        op.f("ix_prompt_version_source_snapshots_source_reference_id"),
        table_name="prompt_version_source_snapshots",
    )
    op.drop_index(
        op.f("ix_prompt_version_source_snapshots_prompt_version_id"),
        table_name="prompt_version_source_snapshots",
    )
    op.drop_table("prompt_version_source_snapshots")
