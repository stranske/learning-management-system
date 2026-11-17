"""Store immutable task metadata on each prompt version.

Revision ID: 20261118_0038
Revises: 20261117_0037
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261118_0038"
down_revision = "20261117_0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Leave historical versions without recoverable task context."""
    op.add_column("prompt_versions", sa.Column("task_context", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("prompt_versions", "task_context")