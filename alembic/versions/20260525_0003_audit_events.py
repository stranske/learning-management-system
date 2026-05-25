"""Audit events table for authoring action logging.

Revision ID: 20260525_0003
Revises: 20260525_0002
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260525_0003"
down_revision = "20260525_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the ``audit_events`` table and supporting indexes."""
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("actor_id", sa.String(length=255), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.String(length=255), nullable=False),
        sa.Column("before_summary", sa.JSON(), nullable=True),
        sa.Column("after_summary", sa.JSON(), nullable=True),
        sa.Column("source_subsystem", sa.String(length=64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_events")),
    )
    op.create_index(
        op.f("ix_audit_events_actor_id"),
        "audit_events",
        ["actor_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_audit_events_entity_type"),
        "audit_events",
        ["entity_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_audit_events_entity_id"),
        "audit_events",
        ["entity_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_audit_events_source_subsystem"),
        "audit_events",
        ["source_subsystem"],
        unique=False,
    )
    op.create_index(
        op.f("ix_audit_events_occurred_at"),
        "audit_events",
        ["occurred_at"],
        unique=False,
    )


def downgrade() -> None:
    """Drop the ``audit_events`` table and supporting indexes."""
    op.drop_index(op.f("ix_audit_events_occurred_at"), table_name="audit_events")
    op.drop_index(op.f("ix_audit_events_source_subsystem"), table_name="audit_events")
    op.drop_index(op.f("ix_audit_events_entity_id"), table_name="audit_events")
    op.drop_index(op.f("ix_audit_events_entity_type"), table_name="audit_events")
    op.drop_index(op.f("ix_audit_events_actor_id"), table_name="audit_events")
    op.drop_table("audit_events")
