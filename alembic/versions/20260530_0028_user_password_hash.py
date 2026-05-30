"""Add nullable password_hash column for local Argon2 login (#180).

Revision ID: 20260530_0028_user_password_hash
Revises: 20260527_0027_case_work_products
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260530_0028_user_password_hash"
down_revision = "20260527_0027_case_work_products"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add nullable ``password_hash`` column to the ``users`` table.

    The column is nullable so the existing local-dev shortcut user can remain
    in the database without a password — the login flow is gated by
    ``Settings.auth_required`` being true on the deployed instance only.
    """
    op.add_column(
        "users",
        sa.Column("password_hash", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    """Drop the ``password_hash`` column."""
    op.drop_column("users", "password_hash")
