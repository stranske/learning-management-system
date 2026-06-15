"""Add LLM interaction skills and feedback events.

Revision ID: 20260527_0026_llm_feedback_events
Revises: 20260526_0025_hints_model_answers
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260527_0026_llm_feedback_events"
down_revision = "20260526_0025_hints_model_answers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create LLM learning-skill and per-turn feedback fact tables."""
    op.create_table(
        "learning_interaction_skills",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("policy_version", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("allowed_trace_classes", sa.JSON(), nullable=False),
        sa.Column(
            "source_citation_required",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "mode IN ('study-coach', 'practice', 'transfer', 'authoring-assist')",
            name=op.f("ck_learning_interaction_skills_mode_valid"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "name", "policy_version", name="learning_interaction_skill_name_version"
        ),
    )
    for column in ("name", "mode", "policy_version", "active", "created_at"):
        op.create_index(
            op.f(f"ix_learning_interaction_skills_{column}"),
            "learning_interaction_skills",
            [column],
        )

    op.create_table(
        "llm_feedback_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("llm_session_id", sa.String(length=36), nullable=False),
        sa.Column("learner_id", sa.String(length=36), nullable=False),
        sa.Column("skill_id", sa.String(length=36), nullable=True),
        sa.Column("feedback_record_id", sa.String(length=36), nullable=True),
        sa.Column("evidence_record_id", sa.String(length=36), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("trace_class", sa.String(length=32), nullable=False),
        sa.Column("source_reference_ids", sa.JSON(), nullable=False),
        sa.Column("unverified", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("cost_metadata", sa.JSON(), nullable=False),
        sa.Column("event_summary", sa.Text(), nullable=True),
        sa.Column("event_body", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "event_type IN ("
            "'learning-policy-nudge', 'feedback-outcome', "
            "'source-citation-check', 'manual-review'"
            ")",
            name=op.f("ck_llm_feedback_events_llm_feedback_event_type_valid"),
        ),
        sa.CheckConstraint(
            "trace_class IN ('evidence-grade', 'formative', 'ephemeral')",
            name=op.f("ck_llm_feedback_events_llm_feedback_event_trace_class_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["evidence_record_id"], ["evidence_records.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["feedback_record_id"], ["feedback_records.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["llm_session_id"],
            ["llm_sessions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["skill_id"],
            ["learning_interaction_skills.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "llm_session_id",
        "learner_id",
        "skill_id",
        "feedback_record_id",
        "evidence_record_id",
        "event_type",
        "trace_class",
        "unverified",
        "created_at",
    ):
        op.create_index(op.f(f"ix_llm_feedback_events_{column}"), "llm_feedback_events", [column])


def downgrade() -> None:
    """Drop LLM learning-skill and feedback fact tables."""
    for column in (
        "created_at",
        "unverified",
        "trace_class",
        "event_type",
        "evidence_record_id",
        "feedback_record_id",
        "skill_id",
        "learner_id",
        "llm_session_id",
    ):
        op.drop_index(op.f(f"ix_llm_feedback_events_{column}"), table_name="llm_feedback_events")
    op.drop_table("llm_feedback_events")

    for column in ("created_at", "active", "policy_version", "mode", "name"):
        op.drop_index(
            op.f(f"ix_learning_interaction_skills_{column}"),
            table_name="learning_interaction_skills",
        )
    op.drop_table("learning_interaction_skills")
