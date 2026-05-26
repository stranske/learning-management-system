"""Add transfer case shells.

Revision ID: 20260526_0020_transfer_cases
Revises: 20260526_0020_capability_estimates
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260526_0020_transfer_cases"
down_revision = "20260526_0020_capability_estimates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create case shell tables."""
    op.create_table(
        "cases",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("ownership_scope", sa.String(length=32), nullable=False),
        sa.Column("rubric_id", sa.String(length=36), nullable=True),
        sa.Column("knowledge_node_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=32), server_default="draft", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("ownership_scope IN ('personal', 'institutional')", name=op.f("ck_cases_case_ownership_scope_valid")),
        sa.CheckConstraint("status IN ('draft', 'published', 'archived')", name=op.f("ck_cases_case_status_valid")),
        sa.ForeignKeyConstraint(["knowledge_node_id"], ["knowledge_nodes.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["rubric_id"], ["rubrics.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("title", "ownership_scope", "rubric_id", "knowledge_node_id", "status"):
        op.create_index(op.f(f"ix_cases_{column}"), "cases", [column])
    op.create_index(op.f("ix_cases_created_at"), "cases", ["created_at"])

    op.create_table(
        "case_steps",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("case_id", sa.String(length=36), nullable=False),
        sa.Column("step_order", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("expected_work_product", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("step_order >= 1", name=op.f("ck_case_steps_case_step_order_positive")),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("case_id", "step_order", name=op.f("uq_case_steps_case_id")),
    )
    op.create_index(op.f("ix_case_steps_case_id"), "case_steps", ["case_id"])

    op.create_table(
        "evidence_packets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("case_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("source_reference_id", sa.String(length=36), nullable=True),
        sa.Column("packet_metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_reference_id"], ["source_references.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_evidence_packets_case_id"), "evidence_packets", ["case_id"])
    op.create_index(op.f("ix_evidence_packets_source_reference_id"), "evidence_packets", ["source_reference_id"])

    op.create_table(
        "decision_points",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("case_step_id", sa.String(length=36), nullable=False),
        sa.Column("evidence_packet_id", sa.String(length=36), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("decision_type", sa.String(length=32), nullable=False),
        sa.Column("options", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "decision_type IN ('single-choice', 'free-response', 'evidence-selection')",
            name=op.f("ck_decision_points_decision_point_type_valid"),
        ),
        sa.ForeignKeyConstraint(["case_step_id"], ["case_steps.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["evidence_packet_id"], ["evidence_packets.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_decision_points_case_step_id"), "decision_points", ["case_step_id"])
    op.create_index(op.f("ix_decision_points_evidence_packet_id"), "decision_points", ["evidence_packet_id"])


def downgrade() -> None:
    """Drop case shell tables."""
    op.drop_index(op.f("ix_decision_points_evidence_packet_id"), table_name="decision_points")
    op.drop_index(op.f("ix_decision_points_case_step_id"), table_name="decision_points")
    op.drop_table("decision_points")
    op.drop_index(op.f("ix_evidence_packets_source_reference_id"), table_name="evidence_packets")
    op.drop_index(op.f("ix_evidence_packets_case_id"), table_name="evidence_packets")
    op.drop_table("evidence_packets")
    op.drop_index(op.f("ix_case_steps_case_id"), table_name="case_steps")
    op.drop_table("case_steps")
    op.drop_index(op.f("ix_cases_created_at"), table_name="cases")
    for column in ("status", "knowledge_node_id", "rubric_id", "ownership_scope", "title"):
        op.drop_index(op.f(f"ix_cases_{column}"), table_name="cases")
    op.drop_table("cases")
