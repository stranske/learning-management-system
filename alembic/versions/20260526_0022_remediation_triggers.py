"""Add misconception patterns and remediation triggers.

Revision ID: 20260526_0022_remediation_triggers
Revises: 20260526_0022_gap_analysis_scope_constraint_cleanup
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260526_0022_remediation_triggers"
down_revision = "20260526_0022_gap_analysis_scope_constraint_cleanup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create deterministic feedback and remediation trigger tables."""
    op.create_table(
        "misconception_patterns",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("pattern_label", sa.String(length=255), nullable=False),
        sa.Column("wrong_answer_signature", sa.Text(), nullable=False),
        sa.Column("diagnosis_text", sa.Text(), nullable=False),
        sa.Column("target_knowledge_node_id", sa.String(length=36), nullable=True),
        sa.Column("ownership_scope", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("suggested_feedback_action_type", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "ownership_scope IN ('personal', 'institutional')",
            name=op.f("ck_misconception_patterns_ownership_scope_valid"),
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0)",
            name=op.f("ck_misconception_patterns_confidence_unit_interval"),
        ),
        sa.CheckConstraint(
            "suggested_feedback_action_type IN ('retry', 'parallel-prompt', "
            "'prerequisite-remediation', 'model-comparison', 'revision', "
            "'coach-review', 'author-review')",
            name=op.f("ck_misconception_patterns_action_type_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["target_knowledge_node_id"], ["knowledge_nodes.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "pattern_label",
        "target_knowledge_node_id",
        "ownership_scope",
        "created_at",
    ):
        op.create_index(
            op.f(f"ix_misconception_patterns_{column}"), "misconception_patterns", [column]
        )

    op.create_table(
        "remediation_triggers",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("pattern_id", sa.String(length=36), nullable=True),
        sa.Column("knowledge_node_id", sa.String(length=36), nullable=False),
        sa.Column("trigger_type", sa.String(length=64), nullable=False),
        sa.Column("trigger_rules", sa.JSON(), nullable=False),
        sa.Column("ownership_scope", sa.String(length=32), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "trigger_type IN ('failed-prerequisite', 'repeated-incorrect-attempts', "
            "'high-confidence-error', 'hint-dependence', 'manual-author-flag')",
            name=op.f("ck_remediation_triggers_remediation_trigger_type_valid"),
        ),
        sa.CheckConstraint(
            "ownership_scope IN ('personal', 'institutional')",
            name=op.f("ck_remediation_triggers_ownership_scope_valid"),
        ),
        sa.ForeignKeyConstraint(["knowledge_node_id"], ["knowledge_nodes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["pattern_id"], ["misconception_patterns.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "pattern_id",
        "knowledge_node_id",
        "trigger_type",
        "ownership_scope",
        "is_active",
        "created_at",
    ):
        op.create_index(op.f(f"ix_remediation_triggers_{column}"), "remediation_triggers", [column])


def downgrade() -> None:
    """Drop remediation trigger and misconception pattern tables."""
    for column in (
        "created_at",
        "is_active",
        "ownership_scope",
        "trigger_type",
        "knowledge_node_id",
        "pattern_id",
    ):
        op.drop_index(op.f(f"ix_remediation_triggers_{column}"), table_name="remediation_triggers")
    op.drop_table("remediation_triggers")
    for column in (
        "created_at",
        "ownership_scope",
        "target_knowledge_node_id",
        "pattern_label",
    ):
        op.drop_index(
            op.f(f"ix_misconception_patterns_{column}"),
            table_name="misconception_patterns",
        )
    op.drop_table("misconception_patterns")
