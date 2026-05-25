"""Create evidence records table.

Revision ID: 20260525_0008_evidence_records
Revises: 20260525_0006_attempts
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260525_0008_evidence_records"
down_revision = "20260525_0006_attempts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create verbose evidence records for mastery estimation."""
    op.create_table(
        "evidence_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("attempt_id", sa.String(length=36), nullable=True),
        sa.Column("learner_id", sa.String(length=36), nullable=False),
        sa.Column("knowledge_node_id", sa.String(length=36), nullable=False),
        sa.Column("prompt_id", sa.String(length=36), nullable=True),
        sa.Column("prompt_version_id", sa.String(length=36), nullable=True),
        sa.Column(
            "evidence_kind",
            sa.String(length=32),
            server_default=sa.text("'observed'"),
            nullable=False,
        ),
        sa.Column(
            "observed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("demand_level", sa.String(length=32), nullable=True),
        sa.Column("knowledge_type", sa.String(length=32), nullable=True),
        sa.Column("time_since_last_attempt_seconds", sa.Integer(), nullable=True),
        sa.Column("response_time_seconds", sa.Integer(), nullable=True),
        sa.Column("correctness", sa.Boolean(), nullable=True),
        sa.Column("confidence_rating", sa.Integer(), nullable=True),
        sa.Column("reference_accessed", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("hint_used", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column(
            "support_level", sa.String(length=32), server_default=sa.text("'none'"), nullable=False
        ),
        sa.Column("retrieval_demand", sa.String(length=64), nullable=True),
        sa.Column("transfer_distance", sa.String(length=64), nullable=True),
        sa.Column("source_match_quality", sa.String(length=64), nullable=True),
        sa.Column("scorer_metadata", sa.JSON(), nullable=True),
        sa.Column("raw_score", sa.Float(), nullable=True),
        sa.Column("normalized_score", sa.Float(), nullable=True),
        sa.Column("max_score", sa.Float(), nullable=True),
        sa.Column("partial_credit_dimensions", sa.JSON(), nullable=True),
        sa.Column("item_difficulty_estimate", sa.Float(), nullable=True),
        sa.Column("attempt_context", sa.JSON(), nullable=True),
        sa.Column("validity_scope", sa.Text(), nullable=True),
        sa.Column("answer_artifact_ref", sa.String(length=1024), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "evidence_kind IN ('observed', 'inferred')",
            name=op.f("ck_evidence_records_evidence_kind_valid"),
        ),
        sa.CheckConstraint(
            "demand_level IS NULL OR demand_level IN ('low', 'medium', 'high')",
            name=op.f("ck_evidence_records_demand_level_valid"),
        ),
        sa.CheckConstraint(
            "knowledge_type IS NULL OR knowledge_type IN "
            "('factual', 'conceptual', 'procedural', 'judgment', 'metacognitive', "
            "'social', 'compliance')",
            name=op.f("ck_evidence_records_knowledge_type_valid"),
        ),
        sa.CheckConstraint(
            "time_since_last_attempt_seconds IS NULL OR time_since_last_attempt_seconds >= 0",
            name=op.f("ck_evidence_records_time_since_last_attempt_non_negative"),
        ),
        sa.CheckConstraint(
            "response_time_seconds IS NULL OR response_time_seconds >= 0",
            name=op.f("ck_evidence_records_response_time_non_negative"),
        ),
        sa.CheckConstraint(
            "confidence_rating IS NULL OR (confidence_rating >= 1 AND confidence_rating <= 5)",
            name=op.f("ck_evidence_records_confidence_rating_valid"),
        ),
        sa.CheckConstraint(
            "support_level IN ('none', 'hint', 'reference', 'worked-example', 'coach')",
            name=op.f("ck_evidence_records_support_level_valid"),
        ),
        sa.CheckConstraint(
            "raw_score IS NULL OR raw_score >= 0",
            name=op.f("ck_evidence_records_raw_score_non_negative"),
        ),
        sa.CheckConstraint(
            "normalized_score IS NULL OR (normalized_score >= 0.0 AND normalized_score <= 1.0)",
            name=op.f("ck_evidence_records_normalized_score_unit_interval"),
        ),
        sa.CheckConstraint(
            "max_score IS NULL OR max_score > 0",
            name=op.f("ck_evidence_records_max_score_positive"),
        ),
        sa.CheckConstraint(
            "item_difficulty_estimate IS NULL OR "
            "(item_difficulty_estimate >= 0.0 AND item_difficulty_estimate <= 1.0)",
            name=op.f("ck_evidence_records_item_difficulty_unit_interval"),
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["attempts.id"],
            name=op.f("fk_evidence_records_attempt_id_attempts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evidence_records")),
    )
    op.create_index(op.f("ix_evidence_records_attempt_id"), "evidence_records", ["attempt_id"])
    op.create_index(op.f("ix_evidence_records_learner_id"), "evidence_records", ["learner_id"])
    op.create_index(
        op.f("ix_evidence_records_knowledge_node_id"),
        "evidence_records",
        ["knowledge_node_id"],
    )
    op.create_index(op.f("ix_evidence_records_prompt_id"), "evidence_records", ["prompt_id"])
    op.create_index(
        op.f("ix_evidence_records_prompt_version_id"),
        "evidence_records",
        ["prompt_version_id"],
    )
    op.create_index(
        op.f("ix_evidence_records_evidence_kind"),
        "evidence_records",
        ["evidence_kind"],
    )
    op.create_index(op.f("ix_evidence_records_observed_at"), "evidence_records", ["observed_at"])
    op.create_index(op.f("ix_evidence_records_demand_level"), "evidence_records", ["demand_level"])
    op.create_index(
        op.f("ix_evidence_records_knowledge_type"),
        "evidence_records",
        ["knowledge_type"],
    )
    op.create_index(
        op.f("ix_evidence_records_reference_accessed"),
        "evidence_records",
        ["reference_accessed"],
    )
    op.create_index(
        op.f("ix_evidence_records_support_level"),
        "evidence_records",
        ["support_level"],
    )


def downgrade() -> None:
    """Drop verbose evidence records."""
    op.drop_index(op.f("ix_evidence_records_support_level"), table_name="evidence_records")
    op.drop_index(op.f("ix_evidence_records_reference_accessed"), table_name="evidence_records")
    op.drop_index(op.f("ix_evidence_records_knowledge_type"), table_name="evidence_records")
    op.drop_index(op.f("ix_evidence_records_demand_level"), table_name="evidence_records")
    op.drop_index(op.f("ix_evidence_records_observed_at"), table_name="evidence_records")
    op.drop_index(op.f("ix_evidence_records_evidence_kind"), table_name="evidence_records")
    op.drop_index(op.f("ix_evidence_records_prompt_version_id"), table_name="evidence_records")
    op.drop_index(op.f("ix_evidence_records_prompt_id"), table_name="evidence_records")
    op.drop_index(op.f("ix_evidence_records_knowledge_node_id"), table_name="evidence_records")
    op.drop_index(op.f("ix_evidence_records_learner_id"), table_name="evidence_records")
    op.drop_index(op.f("ix_evidence_records_attempt_id"), table_name="evidence_records")
    op.drop_table("evidence_records")
