"""Add reusable feedback templates.

Revision ID: 20260526_0024_feedback_templates
Revises: 20260526_0023_maintenance_plans
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260526_0024_feedback_templates"
down_revision = "20260526_0023_maintenance_plans"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create reusable feedback template table."""
    op.create_table(
        "feedback_templates",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("template_body", sa.Text(), nullable=False),
        sa.Column("placeholder_schema", sa.JSON(), nullable=False),
        sa.Column("feedback_level", sa.String(length=32), nullable=False),
        sa.Column("action_type", sa.String(length=64), nullable=False),
        sa.Column("ownership_scope", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="draft", nullable=False),
        sa.Column("authoring_actor", sa.String(length=255), nullable=False),
        sa.Column("misconception_pattern_id", sa.String(length=36), nullable=True),
        sa.Column("feedback_action_id", sa.String(length=36), nullable=True),
        sa.Column("knowledge_node_ids", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "ownership_scope IN ('personal', 'institutional')",
            name=op.f("ck_feedback_templates_feedback_template_ownership_scope_valid"),
        ),
        sa.CheckConstraint(
            "feedback_level IN ('affirmation', 'coaching', 'remediation', 'review')",
            name=op.f("ck_feedback_templates_feedback_template_level_valid"),
        ),
        sa.CheckConstraint(
            "action_type IN ('retry', 'parallel-prompt', 'prerequisite-remediation', "
            "'model-comparison', 'revision', 'coach-review', 'author-review')",
            name=op.f("ck_feedback_templates_feedback_template_action_type_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'published', 'archived')",
            name=op.f("ck_feedback_templates_feedback_template_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["misconception_pattern_id"], ["misconception_patterns.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["feedback_action_id"], ["feedback_actions.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "name",
        "feedback_level",
        "action_type",
        "ownership_scope",
        "status",
        "misconception_pattern_id",
        "feedback_action_id",
        "created_at",
    ):
        op.create_index(op.f(f"ix_feedback_templates_{column}"), "feedback_templates", [column])


def downgrade() -> None:
    """Drop reusable feedback template table."""
    for column in (
        "created_at",
        "feedback_action_id",
        "misconception_pattern_id",
        "status",
        "ownership_scope",
        "action_type",
        "feedback_level",
        "name",
    ):
        op.drop_index(op.f(f"ix_feedback_templates_{column}"), table_name="feedback_templates")
    op.drop_table("feedback_templates")
