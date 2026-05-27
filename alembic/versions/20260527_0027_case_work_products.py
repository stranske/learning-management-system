"""Add case work products.

Revision ID: 20260527_0027_case_work_products
Revises: 20260527_0027_merge_revision_requests_llm_feedback_events
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260527_0027_case_work_products"
down_revision = "20260527_0027_merge_revision_requests_llm_feedback_events"
branch_labels = None
depends_on = None

_INDEXED_COLUMNS = (
    "case_id",
    "case_step_id",
    "learner_id",
    "rubric_id",
    "prompt_id",
    "submission_type",
    "status",
    "rubric_score_id",
    "revision_request_id",
    "submitted_at",
)


def upgrade() -> None:
    """Create the work_products table for scored transfer-case submissions."""
    op.create_table(
        "work_products",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("case_id", sa.String(length=36), nullable=False),
        sa.Column("case_step_id", sa.String(length=36), nullable=True),
        sa.Column("learner_id", sa.String(length=36), nullable=False),
        sa.Column("rubric_id", sa.String(length=36), nullable=True),
        sa.Column("prompt_id", sa.String(length=36), nullable=True),
        sa.Column("submission_type", sa.String(length=32), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("artifact_ref", sa.String(length=1024), nullable=True),
        sa.Column("status", sa.String(length=32), server_default="submitted", nullable=False),
        sa.Column("rubric_score_id", sa.String(length=36), nullable=True),
        sa.Column("revision_request_id", sa.String(length=36), nullable=True),
        sa.Column(
            "submitted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "submission_type IN ('memo', 'rationale', 'classification', "
            "'analysis', 'artifact', 'other')",
            name=op.f("ck_work_products_work_product_submission_type_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'submitted', 'scored', 'revision-requested', "
            "'accepted', 'withdrawn')",
            name=op.f("ck_work_products_work_product_status_valid"),
        ),
        sa.CheckConstraint(
            "body IS NOT NULL OR artifact_ref IS NOT NULL",
            name=op.f("ck_work_products_work_product_body_or_artifact_present"),
        ),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["case_step_id"], ["case_steps.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["rubric_id"], ["rubrics.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["rubric_score_id"], ["rubric_scores.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["revision_request_id"], ["revision_requests.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in _INDEXED_COLUMNS:
        op.create_index(op.f(f"ix_work_products_{column}"), "work_products", [column])


def downgrade() -> None:
    """Drop the work_products table."""
    for column in reversed(_INDEXED_COLUMNS):
        op.drop_index(op.f(f"ix_work_products_{column}"), table_name="work_products")
    op.drop_table("work_products")
