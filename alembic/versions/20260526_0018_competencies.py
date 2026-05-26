"""Add competencies and competency evidence.

Revision ID: 20260526_0018_competencies
Revises: 20260526_0017_rubric_scores
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260526_0018_competencies"
down_revision = "20260526_0017_rubric_scores"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create competency tables."""
    op.create_table(
        "competencies",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("ownership_scope", sa.String(length=32), nullable=False),
        sa.Column("target_knowledge_type", sa.String(length=32), nullable=False),
        sa.Column("validity_scope", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), server_default="draft", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "ownership_scope IN ('personal', 'institutional')",
            name=op.f("ck_competencies_ownership_scope_valid"),
        ),
        sa.CheckConstraint(
            "target_knowledge_type IN ('factual', 'conceptual', 'procedural', 'judgment', "
            "'metacognitive', 'social', 'compliance')",
            name=op.f("ck_competencies_target_knowledge_type_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'deprecated')",
            name=op.f("ck_competencies_status_valid"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "title",
        "ownership_scope",
        "target_knowledge_type",
        "status",
        "created_at",
    ):
        op.create_index(op.f(f"ix_competencies_{column}"), "competencies", [column])

    op.create_table(
        "competency_evidence",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("competency_id", sa.String(length=36), nullable=False),
        sa.Column("knowledge_node_id", sa.String(length=36), nullable=False),
        sa.Column("evidence_record_id", sa.String(length=36), nullable=False),
        sa.Column("learner_id", sa.String(length=36), nullable=False),
        sa.Column(
            "contribution_weight", sa.Float(), server_default="1.0", nullable=False
        ),
        sa.Column("evidence_role", sa.String(length=32), server_default="supports", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "evidence_role IN ('supports', 'contradicts', 'demonstrates', 'prerequisite')",
            name=op.f("ck_competency_evidence_evidence_role_valid"),
        ),
        sa.CheckConstraint(
            "contribution_weight >= 0.0 AND contribution_weight <= 1.0",
            name=op.f("ck_competency_evidence_contribution_weight_unit_interval"),
        ),
        sa.ForeignKeyConstraint(["competency_id"], ["competencies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["evidence_record_id"], ["evidence_records.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["knowledge_node_id"], ["knowledge_nodes.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "competency_id",
        "knowledge_node_id",
        "evidence_record_id",
        "learner_id",
        "evidence_role",
        "created_at",
    ):
        op.create_index(op.f(f"ix_competency_evidence_{column}"), "competency_evidence", [column])


def downgrade() -> None:
    """Drop competency tables."""
    for column in (
        "created_at",
        "evidence_role",
        "learner_id",
        "evidence_record_id",
        "knowledge_node_id",
        "competency_id",
    ):
        op.drop_index(op.f(f"ix_competency_evidence_{column}"), table_name="competency_evidence")
    op.drop_table("competency_evidence")
    for column in (
        "created_at",
        "status",
        "target_knowledge_type",
        "ownership_scope",
        "title",
    ):
        op.drop_index(op.f(f"ix_competencies_{column}"), table_name="competencies")
    op.drop_table("competencies")

