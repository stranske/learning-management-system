"""Add rubrics and criteria.

Revision ID: 20260526_0016_rubrics
Revises: 20260525_0015_feedback_records
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260526_0016_rubrics"
down_revision = "20260525_0015_feedback_records"
branch_labels = None
depends_on = None

RUBRIC_STATUSES = ("draft", "published", "archived")
RUBRIC_CRITERION_STATUSES = ("active", "archived")


def _sql_values(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    """Create rubric and rubric criterion tables."""
    op.create_table(
        "rubrics",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("ownership_scope", sa.String(length=32), nullable=False),
        sa.Column("prompt_id", sa.String(length=36), nullable=True),
        sa.Column("knowledge_node_id", sa.String(length=36), nullable=True),
        sa.Column("case_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=32), server_default=sa.text("'draft'"), nullable=False),
        sa.Column("authoring_actor", sa.String(length=255), nullable=False),
        sa.Column("reviewing_actor", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "ownership_scope IN ('personal', 'institutional')",
            name=op.f("ck_rubrics_rubric_ownership_scope_valid"),
        ),
        sa.CheckConstraint(
            f"status IN ({_sql_values(RUBRIC_STATUSES)})",
            name=op.f("ck_rubrics_rubric_status_valid"),
        ),
        sa.ForeignKeyConstraint(["knowledge_node_id"], ["knowledge_nodes.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["prompt_id"], ["prompts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "title",
        "ownership_scope",
        "prompt_id",
        "knowledge_node_id",
        "case_id",
        "status",
        "created_at",
    ):
        op.create_index(op.f(f"ix_rubrics_{column}"), "rubrics", [column])

    op.create_table(
        "rubric_criteria",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("rubric_id", sa.String(length=36), nullable=False),
        sa.Column("criterion_order", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("max_points", sa.Float(), nullable=False),
        sa.Column("performance_levels", sa.JSON(), nullable=False),
        sa.Column("validity_scope", sa.String(length=255), nullable=True),
        sa.Column(
            "status", sa.String(length=32), server_default=sa.text("'active'"), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "criterion_order >= 1",
            name=op.f("ck_rubric_criteria_rubric_criterion_order_positive"),
        ),
        sa.CheckConstraint(
            "max_points > 0",
            name=op.f("ck_rubric_criteria_rubric_criterion_max_points_positive"),
        ),
        sa.CheckConstraint(
            f"status IN ({_sql_values(RUBRIC_CRITERION_STATUSES)})",
            name=op.f("ck_rubric_criteria_rubric_criterion_status_valid"),
        ),
        sa.ForeignKeyConstraint(["rubric_id"], ["rubrics.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "rubric_id",
            "criterion_order",
            name=op.f("uq_rubric_criteria_rubric_id"),
        ),
    )
    for column in ("rubric_id", "status", "created_at"):
        op.create_index(op.f(f"ix_rubric_criteria_{column}"), "rubric_criteria", [column])


def downgrade() -> None:
    """Drop rubric and rubric criterion tables."""
    for column in ("created_at", "status", "rubric_id"):
        op.drop_index(op.f(f"ix_rubric_criteria_{column}"), table_name="rubric_criteria")
    op.drop_table("rubric_criteria")

    for column in (
        "created_at",
        "status",
        "case_id",
        "knowledge_node_id",
        "prompt_id",
        "ownership_scope",
        "title",
    ):
        op.drop_index(op.f(f"ix_rubrics_{column}"), table_name="rubrics")
    op.drop_table("rubrics")
