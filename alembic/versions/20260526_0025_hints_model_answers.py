"""Add hints and model answers.

Revision ID: 20260526_0025_hints_model_answers
Revises: 20260526_0024_feedback_templates
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260526_0025_hints_model_answers"
down_revision = "20260526_0024_feedback_templates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create prompt hint/model-answer and reveal audit tables."""
    op.create_table(
        "hints",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("prompt_id", sa.String(length=36), nullable=False),
        sa.Column("hint_text", sa.Text(), nullable=False),
        sa.Column("reveal_order", sa.Integer(), nullable=False),
        sa.Column("support_level", sa.String(length=32), server_default="hint", nullable=False),
        sa.Column(
            "reveal_policy",
            sa.String(length=32),
            server_default="after-attempt",
            nullable=False,
        ),
        sa.Column("source_citation_metadata", sa.JSON(), nullable=True),
        sa.Column("authoring_actor", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("reveal_order >= 1", name=op.f("ck_hints_hint_reveal_order_positive")),
        sa.CheckConstraint(
            "support_level IN ('hint', 'reference', 'worked-example', 'coach')",
            name=op.f("ck_hints_hint_support_level_valid"),
        ),
        sa.CheckConstraint(
            "reveal_policy IN ('after-attempt', 'always', 'instructor-only', 'system-triggered')",
            name=op.f("ck_hints_hint_reveal_policy_valid"),
        ),
        sa.ForeignKeyConstraint(["prompt_id"], ["prompts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("prompt_id", "reveal_order", name="hint_prompt_reveal_order_unique"),
    )
    for column in ("prompt_id", "support_level", "reveal_policy", "created_at"):
        op.create_index(op.f(f"ix_hints_{column}"), "hints", [column])

    op.create_table(
        "model_answers",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("prompt_id", sa.String(length=36), nullable=False),
        sa.Column("rubric_id", sa.String(length=36), nullable=True),
        sa.Column("answer_body", sa.Text(), nullable=False),
        sa.Column(
            "reveal_policy",
            sa.String(length=32),
            server_default="after-attempt",
            nullable=False,
        ),
        sa.Column("source_citation_metadata", sa.JSON(), nullable=True),
        sa.Column("authoring_actor", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "reveal_policy IN ('after-attempt', 'always', 'instructor-only', 'system-triggered')",
            name=op.f("ck_model_answers_model_answer_reveal_policy_valid"),
        ),
        sa.ForeignKeyConstraint(["prompt_id"], ["prompts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["rubric_id"], ["rubrics.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("prompt_id", "rubric_id", "reveal_policy", "created_at"):
        op.create_index(op.f(f"ix_model_answers_{column}"), "model_answers", [column])

    op.create_table(
        "hint_reveals",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("hint_id", sa.String(length=36), nullable=False),
        sa.Column("learner_id", sa.String(length=36), nullable=False),
        sa.Column("prompt_id", sa.String(length=36), nullable=False),
        sa.Column("attempt_id", sa.String(length=36), nullable=True),
        sa.Column("initiated_by", sa.String(length=32), nullable=False),
        sa.Column(
            "revealed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "initiated_by IN ('learner', 'system', 'instructor', 'test')",
            name=op.f("ck_hint_reveals_hint_reveal_initiator_valid"),
        ),
        sa.ForeignKeyConstraint(["attempt_id"], ["attempts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["hint_id"], ["hints.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "hint_id",
        "learner_id",
        "prompt_id",
        "attempt_id",
        "initiated_by",
        "revealed_at",
    ):
        op.create_index(op.f(f"ix_hint_reveals_{column}"), "hint_reveals", [column])

    op.create_table(
        "model_answer_reveals",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("model_answer_id", sa.String(length=36), nullable=False),
        sa.Column("learner_id", sa.String(length=36), nullable=False),
        sa.Column("prompt_id", sa.String(length=36), nullable=False),
        sa.Column("attempt_id", sa.String(length=36), nullable=True),
        sa.Column("initiated_by", sa.String(length=32), nullable=False),
        sa.Column(
            "revealed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "initiated_by IN ('learner', 'system', 'instructor', 'test')",
            name=op.f("ck_model_answer_reveals_model_answer_reveal_initiator_valid"),
        ),
        sa.ForeignKeyConstraint(["attempt_id"], ["attempts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["model_answer_id"], ["model_answers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "model_answer_id",
        "learner_id",
        "prompt_id",
        "attempt_id",
        "initiated_by",
        "revealed_at",
    ):
        op.create_index(op.f(f"ix_model_answer_reveals_{column}"), "model_answer_reveals", [column])


def downgrade() -> None:
    """Drop prompt hint/model-answer and reveal audit tables."""
    for column in (
        "revealed_at",
        "initiated_by",
        "attempt_id",
        "prompt_id",
        "learner_id",
        "model_answer_id",
    ):
        op.drop_index(op.f(f"ix_model_answer_reveals_{column}"), table_name="model_answer_reveals")
    op.drop_table("model_answer_reveals")

    for column in (
        "revealed_at",
        "initiated_by",
        "attempt_id",
        "prompt_id",
        "learner_id",
        "hint_id",
    ):
        op.drop_index(op.f(f"ix_hint_reveals_{column}"), table_name="hint_reveals")
    op.drop_table("hint_reveals")

    for column in ("created_at", "reveal_policy", "rubric_id", "prompt_id"):
        op.drop_index(op.f(f"ix_model_answers_{column}"), table_name="model_answers")
    op.drop_table("model_answers")

    for column in ("created_at", "reveal_policy", "support_level", "prompt_id"):
        op.drop_index(op.f(f"ix_hints_{column}"), table_name="hints")
    op.drop_table("hints")
