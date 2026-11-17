"""Save the prompt version and task context observed at attempt creation.

Revision ID: 20261117_0037
Revises: 20260924_0036
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261117_0037"
down_revision = "20260924_0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Leave existing attempts unknown; today's prompt cannot establish their origin."""
    with op.batch_alter_table("attempts") as batch:
        batch.add_column(sa.Column("prompt_version_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("task_context", sa.JSON(), nullable=True))
        batch.create_foreign_key(
            "fk_attempts_prompt_version_id_prompt_versions",
            "prompt_versions",
            ["prompt_version_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.create_index("ix_attempts_prompt_version_id", ["prompt_version_id"])


def downgrade() -> None:
    with op.batch_alter_table("attempts") as batch:
        batch.drop_index("ix_attempts_prompt_version_id")
        batch.drop_constraint("fk_attempts_prompt_version_id_prompt_versions", type_="foreignkey")
        batch.drop_column("task_context")
        batch.drop_column("prompt_version_id")
