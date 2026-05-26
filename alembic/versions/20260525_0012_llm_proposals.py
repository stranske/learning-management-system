"""Create llm_proposals table.

Revision ID: 20260525_0012_llm_proposals
Revises: 20260525_0011_review_queue_items
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260525_0012_llm_proposals"
down_revision = "20260525_0011_review_queue_items"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the llm_proposals table binding LLM sessions to draft artifacts."""
    op.create_table(
        "llm_proposals",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("llm_session_id", sa.String(length=36), nullable=False),
        sa.Column("llm_model", sa.String(length=120), nullable=False),
        sa.Column("proposed_by", sa.String(length=255), nullable=False),
        sa.Column("knowledge_node_id", sa.String(length=36), nullable=True),
        sa.Column("knowledge_edge_id", sa.String(length=36), nullable=True),
        sa.Column("prompt_id", sa.String(length=36), nullable=True),
        sa.Column("source_reference_id", sa.String(length=36), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_llm_proposals")),
        sa.UniqueConstraint(
            "llm_session_id",
            name=op.f("uq_llm_proposals_llm_session_id"),
        ),
        sa.ForeignKeyConstraint(
            ["llm_session_id"],
            ["llm_sessions.id"],
            name=op.f("fk_llm_proposals_llm_session_id_llm_sessions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["knowledge_node_id"],
            ["knowledge_nodes.id"],
            name=op.f("fk_llm_proposals_knowledge_node_id_knowledge_nodes"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["knowledge_edge_id"],
            ["knowledge_edges.id"],
            name=op.f("fk_llm_proposals_knowledge_edge_id_knowledge_edges"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["prompt_id"],
            ["prompts.id"],
            name=op.f("fk_llm_proposals_prompt_id_prompts"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_reference_id"],
            ["source_references.id"],
            name=op.f("fk_llm_proposals_source_reference_id_source_references"),
            ondelete="SET NULL",
        ),
    )
    op.create_index(
        op.f("ix_llm_proposals_llm_session_id"),
        "llm_proposals",
        ["llm_session_id"],
    )
    op.create_index(
        op.f("ix_llm_proposals_proposed_by"),
        "llm_proposals",
        ["proposed_by"],
    )
    op.create_index(
        op.f("ix_llm_proposals_knowledge_node_id"),
        "llm_proposals",
        ["knowledge_node_id"],
    )
    op.create_index(
        op.f("ix_llm_proposals_knowledge_edge_id"),
        "llm_proposals",
        ["knowledge_edge_id"],
    )
    op.create_index(
        op.f("ix_llm_proposals_prompt_id"),
        "llm_proposals",
        ["prompt_id"],
    )
    op.create_index(
        op.f("ix_llm_proposals_source_reference_id"),
        "llm_proposals",
        ["source_reference_id"],
    )


def downgrade() -> None:
    """Drop the llm_proposals table."""
    op.drop_index(op.f("ix_llm_proposals_source_reference_id"), table_name="llm_proposals")
    op.drop_index(op.f("ix_llm_proposals_prompt_id"), table_name="llm_proposals")
    op.drop_index(op.f("ix_llm_proposals_knowledge_edge_id"), table_name="llm_proposals")
    op.drop_index(op.f("ix_llm_proposals_knowledge_node_id"), table_name="llm_proposals")
    op.drop_index(op.f("ix_llm_proposals_proposed_by"), table_name="llm_proposals")
    op.drop_index(op.f("ix_llm_proposals_llm_session_id"), table_name="llm_proposals")
    op.drop_table("llm_proposals")
