"""serialize knowledge-edge invariants across concurrent writers

Revision ID: 20260924_0036
Revises: 20260806_0035
Create Date: 2026-09-24
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260924_0036"
down_revision = "20260806_0035"
branch_labels = None
depends_on = None

EDGE_IDENTITY_COLUMNS = (
    "source_node_id",
    "target_node_id",
    "edge_type",
    "source_scope",
    "target_scope",
)


def _reject_existing_duplicates() -> None:
    connection = op.get_bind()
    grouped_columns = ", ".join(EDGE_IDENTITY_COLUMNS)
    rows = connection.execute(sa.text(f"""
            SELECT {grouped_columns}, COUNT(*) AS copies
            FROM knowledge_edges
            GROUP BY {grouped_columns}
            HAVING COUNT(*) > 1
            ORDER BY copies DESC, {grouped_columns}
            LIMIT 10
            """)).mappings().all()
    if rows:
        examples = "; ".join(
            ", ".join(f"{column}={row[column]!r}" for column in EDGE_IDENTITY_COLUMNS)
            + f", copies={row['copies']}"
            for row in rows
        )
        raise RuntimeError(
            "cannot add uq_knowledge_edges_identity: duplicate knowledge edges exist; "
            f"first {len(rows)} group(s): {examples}"
        )


def upgrade() -> None:
    """Add the duplicate floor and transactional per-scope lock rows."""
    _reject_existing_duplicates()
    op.create_table(
        "knowledge_graph_scope_locks",
        sa.Column("source_scope", sa.String(length=32), primary_key=True),
        sa.Column("lock_token", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint(
            "source_scope IN ('personal', 'institutional')",
            name="scope_valid",
        ),
    )
    lock_table = sa.table(
        "knowledge_graph_scope_locks",
        sa.column("source_scope", sa.String(length=32)),
        sa.column("lock_token", sa.Integer()),
    )
    op.bulk_insert(
        lock_table,
        [
            {"source_scope": "personal", "lock_token": 0},
            {"source_scope": "institutional", "lock_token": 0},
        ],
    )
    with op.batch_alter_table("knowledge_edges") as batch:
        batch.create_unique_constraint("uq_knowledge_edges_identity", EDGE_IDENTITY_COLUMNS)


def downgrade() -> None:
    """Remove edge identity locking infrastructure."""
    with op.batch_alter_table("knowledge_edges") as batch:
        batch.drop_constraint("uq_knowledge_edges_identity", type_="unique")
    op.drop_table("knowledge_graph_scope_locks")
