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
    with op.batch_alter_table("evidence_records") as batch_op:
        batch_op.add_column(sa.Column("scorer_type", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("scorer_id", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("scorer_version", sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column("scoring_method", sa.String(length=32), nullable=True))
        batch_op.create_check_constraint(
            op.f("ck_evidence_records_scorer_type_valid"),
            "scorer_type IS NULL OR scorer_type IN ('auto', 'llm-judge', 'rubric-self', 'human')",
        )
        batch_op.create_check_constraint(
            op.f("ck_evidence_records_scoring_method_valid"),
            "scoring_method IS NULL OR scoring_method IN ('binary', 'partial-credit', 'rubric-scored')",
        )


def downgrade() -> None:
    with op.batch_alter_table("evidence_records") as batch_op:
        batch_op.drop_constraint(
            op.f("ck_evidence_records_scoring_method_valid"),
            type_="check",
        )
        batch_op.drop_constraint(
            op.f("ck_evidence_records_scorer_type_valid"),
            type_="check",
        )
        batch_op.drop_column("scoring_method")
        batch_op.drop_column("scorer_version")
        batch_op.drop_column("scorer_id")
        batch_op.drop_column("scorer_type")
