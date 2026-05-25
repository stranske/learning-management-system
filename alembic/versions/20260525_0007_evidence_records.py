"""Create evidence_records table.

Revision ID: 20260525_0007
Revises: 20260525_0006_attempts
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260525_0007"
down_revision = "20260525_0006_attempts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create verbose evidence records for mastery inputs."""
    op.create_table(
        "evidence_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("learner_id", sa.String(length=36), nullable=False),
        sa.Column("knowledge_node_id", sa.String(length=36), nullable=False),
        sa.Column("prompt_id", sa.String(length=36), nullable=False),
        sa.Column("prompt_version_id", sa.String(length=36), nullable=True),
        sa.Column("attempt_id", sa.String(length=36), nullable=True),
        sa.Column("evidence_kind", sa.String(length=32), server_default="observed", nullable=False),
        sa.Column("demand_level", sa.String(length=32), nullable=False),
        sa.Column("knowledge_type", sa.String(length=32), nullable=False),
        sa.Column("time_since_last_attempt_seconds", sa.Integer(), nullable=True),
        sa.Column("response_time_seconds", sa.Integer(), nullable=True),
        sa.Column("correctness", sa.Boolean(), nullable=True),
        sa.Column("confidence_rating", sa.Integer(), nullable=True),
        sa.Column("hint_used", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("reference_accessed", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("support_level", sa.String(length=32), server_default="none", nullable=False),
        sa.Column("retrieval_demand", sa.String(length=120), nullable=True),
        sa.Column("transfer_distance", sa.String(length=120), nullable=True),
        sa.Column("source_match_quality", sa.String(length=120), nullable=True),
        sa.Column("scorer_id", sa.String(length=255), nullable=True),
        sa.Column("scorer_version", sa.String(length=120), nullable=True),
        sa.Column("raw_score", sa.Float(), nullable=True),
        sa.Column("normalized_score", sa.Float(), nullable=True),
        sa.Column("max_score", sa.Float(), nullable=True),
        sa.Column("partial_credit_dimensions", sa.JSON(), nullable=True),
        sa.Column("item_difficulty_estimate", sa.Float(), nullable=True),
        sa.Column("attempt_context", sa.JSON(), nullable=True),
        sa.Column("validity_scope", sa.String(length=32), server_default="attempt", nullable=False),
        sa.Column("answer_artifact_ref", sa.String(length=1024), nullable=True),
        sa.Column(
            "recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "evidence_kind IN ('observed', 'inferred')",
            name=op.f("ck_evidence_records_evidence_kind_valid"),
        ),
        sa.CheckConstraint(
            "support_level IN ('none', 'hint', 'reference', 'worked-example', 'coach')",
            name=op.f("ck_evidence_records_support_level_valid"),
        ),
        sa.CheckConstraint(
            "validity_scope IN ('attempt', 'session', 'node', 'course')",
            name=op.f("ck_evidence_records_validity_scope_valid"),
        ),
        sa.CheckConstraint(
            "confidence_rating IS NULL OR (confidence_rating >= 1 AND confidence_rating <= 5)",
            name=op.f("ck_evidence_records_confidence_rating_valid"),
        ),
        sa.CheckConstraint(
            "raw_score IS NULL OR max_score IS NULL OR raw_score <= max_score",
            name=op.f("ck_evidence_records_raw_score_not_above_max"),
        ),
        sa.CheckConstraint(
            "normalized_score IS NULL OR (normalized_score >= 0.0 AND normalized_score <= 1.0)",
            name=op.f("ck_evidence_records_normalized_score_unit_interval"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evidence_records")),
    )
    for column in (
        "learner_id",
        "knowledge_node_id",
        "prompt_id",
        "prompt_version_id",
        "attempt_id",
        "evidence_kind",
        "demand_level",
        "knowledge_type",
        "support_level",
        "validity_scope",
        "recorded_at",
    ):
        op.create_index(op.f(f"ix_evidence_records_{column}"), "evidence_records", [column])


def downgrade() -> None:
    """Drop verbose evidence records."""
    for column in (
        "recorded_at",
        "validity_scope",
        "support_level",
        "knowledge_type",
        "demand_level",
        "evidence_kind",
        "attempt_id",
        "prompt_version_id",
        "prompt_id",
        "knowledge_node_id",
        "learner_id",
    ):
        op.drop_index(op.f(f"ix_evidence_records_{column}"), table_name="evidence_records")
    op.drop_table("evidence_records")
