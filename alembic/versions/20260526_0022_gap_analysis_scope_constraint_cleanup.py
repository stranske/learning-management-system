"""Drop redundant gap analysis ownership scope constraint.

Revision ID: 20260526_0022_gap_analysis_scope_constraint_cleanup
Revises: 20260526_0021_gap_analyses
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260526_0022_gap_analysis_scope_constraint_cleanup"
down_revision = "20260526_0021_gap_analyses"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Keep the personal-only invariant without the broader scope check."""
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("gap_analyses") as batch_op:
            batch_op.drop_constraint(
                op.f("ck_gap_analyses_ownership_scope_valid"),
                type_="check",
            )
        return
    op.drop_constraint(
        "ck_gap_analyses_ownership_scope_valid",
        "gap_analyses",
        type_="check",
    )


def downgrade() -> None:
    """Restore the broader scope check for downgrade symmetry."""
    bind = op.get_bind()
    constraint = sa.CheckConstraint(
        "ownership_scope IN ('personal', 'institutional')",
        name="ck_gap_analyses_ownership_scope_valid",
    )
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("gap_analyses") as batch_op:
            batch_op.create_check_constraint(
                op.f(constraint.name),
                constraint.sqltext,
            )
        return
    op.create_check_constraint(
        constraint.name,
        "gap_analyses",
        constraint.sqltext,
    )
