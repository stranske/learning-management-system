"""add scorer typed columns to evidence records

Revision ID: 20260617_0030
Revises: 20260531_0029_learner_reflections
Create Date: 2026-06-17 17:03:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260617_0030"
down_revision = "20260531_0029_learner_reflections"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("evidence_records", sa.Column("scorer_type", sa.String(length=64), nullable=True))
    op.add_column("evidence_records", sa.Column("scorer_id", sa.String(length=255), nullable=True))
    op.add_column(
        "evidence_records", sa.Column("scorer_version", sa.String(length=120), nullable=True)
    )
    op.add_column(
        "evidence_records", sa.Column("scoring_method", sa.String(length=32), nullable=True)
    )
    op.create_check_constraint(
        op.f("ck_evidence_records_scorer_type_valid"),
        "evidence_records",
        "scorer_type IS NULL OR scorer_type IN ('auto', 'llm-judge', 'rubric-self', 'human')",
    )
    op.create_check_constraint(
        op.f("ck_evidence_records_scoring_method_valid"),
        "evidence_records",
        "scoring_method IS NULL OR scoring_method IN ('binary', 'partial-credit', 'rubric-scored')",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_evidence_records_scoring_method_valid"),
        "evidence_records",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_evidence_records_scorer_type_valid"),
        "evidence_records",
        type_="check",
    )
    op.drop_column("evidence_records", "scoring_method")
    op.drop_column("evidence_records", "scorer_version")
    op.drop_column("evidence_records", "scorer_id")
    op.drop_column("evidence_records", "scorer_type")
