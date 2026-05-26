"""Add durable scheduler policy, schedule, and decision records.

Revision ID: 20260525_0014_scheduler_records
Revises: 20260525_0013_llm_learner_controls
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260525_0014_scheduler_records"
down_revision = "20260525_0013_llm_learner_controls"
branch_labels = None
depends_on = None


REASON_CODES = (
    "new-learning",
    "due-review",
    "overdue",
    "remediation",
    "stale",
    "blocked-prerequisite",
)
SCHEDULE_STATES = ("scheduled", "completed", "skipped", "stale")
KNOWLEDGE_TYPES = (
    "factual",
    "conceptual",
    "procedural",
    "judgment",
    "metacognitive",
    "social",
    "compliance",
)
OWNERSHIP_SCOPES = ("personal", "institutional")
SUPPORT_LEVELS = ("none", "hint", "reference", "worked-example", "coach")


def _sql_values(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    """Create scheduler audit tables."""
    op.create_table(
        "review_policies",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=False),
        sa.Column("knowledge_type", sa.String(length=32), nullable=True),
        sa.Column("ownership_scope", sa.String(length=32), nullable=True),
        sa.Column("settings", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            f"reason_code IN ({_sql_values(REASON_CODES)})",
            name=op.f("ck_review_policies_review_policy_reason_code_valid"),
        ),
        sa.CheckConstraint(
            f"knowledge_type IS NULL OR knowledge_type IN ({_sql_values(KNOWLEDGE_TYPES)})",
            name=op.f("ck_review_policies_review_policy_knowledge_type_valid"),
        ),
        sa.CheckConstraint(
            f"ownership_scope IS NULL OR ownership_scope IN ({_sql_values(OWNERSHIP_SCOPES)})",
            name=op.f("ck_review_policies_review_policy_ownership_scope_valid"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_review_policies_created_at"), "review_policies", ["created_at"])
    op.create_index(op.f("ix_review_policies_is_active"), "review_policies", ["is_active"])
    op.create_index(
        op.f("ix_review_policies_policy_version"), "review_policies", ["policy_version"]
    )
    op.create_index(op.f("ix_review_policies_reason_code"), "review_policies", ["reason_code"])
    op.create_index(
        op.f("ix_review_policies_knowledge_type"), "review_policies", ["knowledge_type"]
    )
    op.create_index(
        op.f("ix_review_policies_ownership_scope"), "review_policies", ["ownership_scope"]
    )

    op.create_table(
        "review_schedules",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("learner_id", sa.String(length=36), nullable=False),
        sa.Column("knowledge_node_id", sa.String(length=36), nullable=False),
        sa.Column("review_policy_id", sa.String(length=36), nullable=True),
        sa.Column("review_queue_item_id", sa.String(length=36), nullable=True),
        sa.Column("reason_code", sa.String(length=64), nullable=False),
        sa.Column(
            "schedule_state", sa.String(length=32), server_default="scheduled", nullable=False
        ),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column("knowledge_type", sa.String(length=32), nullable=True),
        sa.Column("ownership_scope", sa.String(length=32), nullable=True),
        sa.Column("source_evidence_record_id", sa.String(length=36), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            f"reason_code IN ({_sql_values(REASON_CODES)})",
            name=op.f("ck_review_schedules_review_schedule_reason_code_valid"),
        ),
        sa.CheckConstraint(
            f"schedule_state IN ({_sql_values(SCHEDULE_STATES)})",
            name=op.f("ck_review_schedules_review_schedule_state_valid"),
        ),
        sa.CheckConstraint(
            f"knowledge_type IS NULL OR knowledge_type IN ({_sql_values(KNOWLEDGE_TYPES)})",
            name=op.f("ck_review_schedules_review_schedule_knowledge_type_valid"),
        ),
        sa.CheckConstraint(
            f"ownership_scope IS NULL OR ownership_scope IN ({_sql_values(OWNERSHIP_SCOPES)})",
            name=op.f("ck_review_schedules_review_schedule_ownership_scope_valid"),
        ),
        sa.ForeignKeyConstraint(["review_policy_id"], ["review_policies.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["review_queue_item_id"], ["review_queue_items.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["source_evidence_record_id"], ["evidence_records.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "learner_id",
        "knowledge_node_id",
        "review_policy_id",
        "review_queue_item_id",
        "reason_code",
        "schedule_state",
        "due_at",
        "policy_version",
        "knowledge_type",
        "ownership_scope",
        "source_evidence_record_id",
        "created_at",
    ):
        op.create_index(op.f(f"ix_review_schedules_{column}"), "review_schedules", [column])

    op.create_table(
        "scheduler_decisions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("learner_id", sa.String(length=36), nullable=False),
        sa.Column("knowledge_node_id", sa.String(length=36), nullable=False),
        sa.Column("review_policy_id", sa.String(length=36), nullable=True),
        sa.Column("review_schedule_id", sa.String(length=36), nullable=True),
        sa.Column("review_queue_item_id", sa.String(length=36), nullable=True),
        sa.Column("source_evidence_record_id", sa.String(length=36), nullable=True),
        sa.Column("reason_code", sa.String(length=64), nullable=False),
        sa.Column("decision_rationale", sa.Text(), nullable=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column("knowledge_type", sa.String(length=32), nullable=True),
        sa.Column("ownership_scope", sa.String(length=32), nullable=True),
        sa.Column("support_level", sa.String(length=32), nullable=True),
        sa.Column("decision_log", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            f"reason_code IN ({_sql_values(REASON_CODES)})",
            name=op.f("ck_scheduler_decisions_scheduler_decision_reason_code_valid"),
        ),
        sa.CheckConstraint(
            f"knowledge_type IS NULL OR knowledge_type IN ({_sql_values(KNOWLEDGE_TYPES)})",
            name=op.f("ck_scheduler_decisions_scheduler_decision_knowledge_type_valid"),
        ),
        sa.CheckConstraint(
            f"ownership_scope IS NULL OR ownership_scope IN ({_sql_values(OWNERSHIP_SCOPES)})",
            name=op.f("ck_scheduler_decisions_scheduler_decision_ownership_scope_valid"),
        ),
        sa.CheckConstraint(
            f"support_level IS NULL OR support_level IN ({_sql_values(SUPPORT_LEVELS)})",
            name=op.f("ck_scheduler_decisions_scheduler_decision_support_level_valid"),
        ),
        sa.ForeignKeyConstraint(["review_policy_id"], ["review_policies.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["review_schedule_id"], ["review_schedules.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["review_queue_item_id"], ["review_queue_items.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["source_evidence_record_id"], ["evidence_records.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "learner_id",
        "knowledge_node_id",
        "review_policy_id",
        "review_schedule_id",
        "review_queue_item_id",
        "source_evidence_record_id",
        "reason_code",
        "policy_version",
        "knowledge_type",
        "ownership_scope",
        "support_level",
        "created_at",
    ):
        op.create_index(op.f(f"ix_scheduler_decisions_{column}"), "scheduler_decisions", [column])


def downgrade() -> None:
    """Drop scheduler audit tables."""
    for column in (
        "created_at",
        "support_level",
        "ownership_scope",
        "knowledge_type",
        "policy_version",
        "reason_code",
        "source_evidence_record_id",
        "review_queue_item_id",
        "review_schedule_id",
        "review_policy_id",
        "knowledge_node_id",
        "learner_id",
    ):
        op.drop_index(op.f(f"ix_scheduler_decisions_{column}"), table_name="scheduler_decisions")
    op.drop_table("scheduler_decisions")

    for column in (
        "created_at",
        "source_evidence_record_id",
        "ownership_scope",
        "knowledge_type",
        "policy_version",
        "due_at",
        "schedule_state",
        "reason_code",
        "review_queue_item_id",
        "review_policy_id",
        "knowledge_node_id",
        "learner_id",
    ):
        op.drop_index(op.f(f"ix_review_schedules_{column}"), table_name="review_schedules")
    op.drop_table("review_schedules")

    op.drop_index(op.f("ix_review_policies_ownership_scope"), table_name="review_policies")
    op.drop_index(op.f("ix_review_policies_knowledge_type"), table_name="review_policies")
    op.drop_index(op.f("ix_review_policies_reason_code"), table_name="review_policies")
    op.drop_index(op.f("ix_review_policies_policy_version"), table_name="review_policies")
    op.drop_index(op.f("ix_review_policies_is_active"), table_name="review_policies")
    op.drop_index(op.f("ix_review_policies_created_at"), table_name="review_policies")
    op.drop_table("review_policies")
