"""Create scoped knowledge graph tables.

Revision ID: 20260525_0005
Revises: 20260525_0004
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260525_0005"
down_revision = "20260525_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create knowledge node, graph reference, and edge tables."""
    op.create_table(
        "knowledge_nodes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(length=2048), nullable=True),
        sa.Column("knowledge_type", sa.String(length=32), nullable=False),
        sa.Column("ownership_scope", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=True),
        sa.Column("imported_from", sa.String(length=1024), nullable=True),
        sa.Column("source_reference_id", sa.String(length=36), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "knowledge_type IN ('concept', 'fact', 'procedure', 'principle', 'question')",
            name=op.f("ck_knowledge_nodes_knowledge_type_valid"),
        ),
        sa.CheckConstraint(
            "ownership_scope IN ('personal', 'institutional')",
            name=op.f("ck_knowledge_nodes_knowledge_node_ownership_scope_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'published', 'archived')",
            name=op.f("ck_knowledge_nodes_knowledge_node_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["source_reference_id"],
            ["source_references.id"],
            name=op.f("fk_knowledge_nodes_source_reference_id_source_references"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_knowledge_nodes")),
    )
    op.create_index(op.f("ix_knowledge_nodes_title"), "knowledge_nodes", ["title"])
    op.create_index(
        op.f("ix_knowledge_nodes_knowledge_type"), "knowledge_nodes", ["knowledge_type"]
    )
    op.create_index(
        op.f("ix_knowledge_nodes_ownership_scope"), "knowledge_nodes", ["ownership_scope"]
    )
    op.create_index(op.f("ix_knowledge_nodes_status"), "knowledge_nodes", ["status"])
    op.create_index(
        op.f("ix_knowledge_nodes_source_reference_id"),
        "knowledge_nodes",
        ["source_reference_id"],
    )
    op.create_index(op.f("ix_knowledge_nodes_created_at"), "knowledge_nodes", ["created_at"])

    op.create_table(
        "graph_references",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("source_scope", sa.String(length=32), nullable=False),
        sa.Column("target_scope", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.String(length=1024), nullable=False),
        sa.Column("actor_id", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "source_scope IN ('personal', 'institutional')",
            name=op.f("ck_graph_references_graph_reference_source_scope_valid"),
        ),
        sa.CheckConstraint(
            "target_scope IN ('personal', 'institutional')",
            name=op.f("ck_graph_references_graph_reference_target_scope_valid"),
        ),
        sa.CheckConstraint(
            "source_scope != target_scope",
            name=op.f("ck_graph_references_graph_reference_cross_scope_only"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_graph_references")),
    )
    op.create_index(op.f("ix_graph_references_source_scope"), "graph_references", ["source_scope"])
    op.create_index(op.f("ix_graph_references_target_scope"), "graph_references", ["target_scope"])

    op.create_table(
        "knowledge_edges",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("source_node_id", sa.String(length=36), nullable=False),
        sa.Column("target_node_id", sa.String(length=36), nullable=False),
        sa.Column("edge_type", sa.String(length=32), nullable=False),
        sa.Column("ownership_scope", sa.String(length=32), nullable=False),
        sa.Column("source_scope", sa.String(length=32), nullable=False),
        sa.Column("target_scope", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=True),
        sa.Column("graph_reference_id", sa.String(length=36), nullable=True),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("updated_by", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "edge_type IN ('prerequisite', 'supports', 'contradicts', 'cross-scope-reference')",
            name=op.f("ck_knowledge_edges_knowledge_edge_type_valid"),
        ),
        sa.CheckConstraint(
            "source_scope IN ('personal', 'institutional')",
            name=op.f("ck_knowledge_edges_knowledge_edge_source_scope_valid"),
        ),
        sa.CheckConstraint(
            "target_scope IN ('personal', 'institutional')",
            name=op.f("ck_knowledge_edges_knowledge_edge_target_scope_valid"),
        ),
        sa.CheckConstraint(
            "ownership_scope IN ('personal', 'institutional')",
            name=op.f("ck_knowledge_edges_knowledge_edge_ownership_scope_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'archived')",
            name=op.f("ck_knowledge_edges_knowledge_edge_status_valid"),
        ),
        sa.CheckConstraint(
            "source_scope = target_scope OR "
            "(edge_type = 'cross-scope-reference' AND graph_reference_id IS NOT NULL)",
            name=op.f("ck_knowledge_edges_knowledge_edge_cross_scope_requires_reference"),
        ),
        sa.ForeignKeyConstraint(
            ["source_node_id"],
            ["knowledge_nodes.id"],
            name=op.f("fk_knowledge_edges_source_node_id_knowledge_nodes"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_node_id"],
            ["knowledge_nodes.id"],
            name=op.f("fk_knowledge_edges_target_node_id_knowledge_nodes"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["graph_reference_id"],
            ["graph_references.id"],
            name=op.f("fk_knowledge_edges_graph_reference_id_graph_references"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_knowledge_edges")),
    )
    op.create_index(
        op.f("ix_knowledge_edges_source_node_id"), "knowledge_edges", ["source_node_id"]
    )
    op.create_index(
        op.f("ix_knowledge_edges_target_node_id"), "knowledge_edges", ["target_node_id"]
    )
    op.create_index(op.f("ix_knowledge_edges_edge_type"), "knowledge_edges", ["edge_type"])
    op.create_index(
        op.f("ix_knowledge_edges_ownership_scope"), "knowledge_edges", ["ownership_scope"]
    )
    op.create_index(op.f("ix_knowledge_edges_source_scope"), "knowledge_edges", ["source_scope"])
    op.create_index(op.f("ix_knowledge_edges_target_scope"), "knowledge_edges", ["target_scope"])
    op.create_index(op.f("ix_knowledge_edges_status"), "knowledge_edges", ["status"])
    op.create_index(
        op.f("ix_knowledge_edges_graph_reference_id"), "knowledge_edges", ["graph_reference_id"]
    )
    op.create_index(op.f("ix_knowledge_edges_created_at"), "knowledge_edges", ["created_at"])


def downgrade() -> None:
    """Drop scoped knowledge graph tables."""
    op.drop_index(op.f("ix_knowledge_edges_created_at"), table_name="knowledge_edges")
    op.drop_index(op.f("ix_knowledge_edges_graph_reference_id"), table_name="knowledge_edges")
    op.drop_index(op.f("ix_knowledge_edges_status"), table_name="knowledge_edges")
    op.drop_index(op.f("ix_knowledge_edges_target_scope"), table_name="knowledge_edges")
    op.drop_index(op.f("ix_knowledge_edges_source_scope"), table_name="knowledge_edges")
    op.drop_index(op.f("ix_knowledge_edges_ownership_scope"), table_name="knowledge_edges")
    op.drop_index(op.f("ix_knowledge_edges_edge_type"), table_name="knowledge_edges")
    op.drop_index(op.f("ix_knowledge_edges_target_node_id"), table_name="knowledge_edges")
    op.drop_index(op.f("ix_knowledge_edges_source_node_id"), table_name="knowledge_edges")
    op.drop_table("knowledge_edges")
    op.drop_index(op.f("ix_graph_references_target_scope"), table_name="graph_references")
    op.drop_index(op.f("ix_graph_references_source_scope"), table_name="graph_references")
    op.drop_table("graph_references")
    op.drop_index(op.f("ix_knowledge_nodes_created_at"), table_name="knowledge_nodes")
    op.drop_index(op.f("ix_knowledge_nodes_source_reference_id"), table_name="knowledge_nodes")
    op.drop_index(op.f("ix_knowledge_nodes_status"), table_name="knowledge_nodes")
    op.drop_index(op.f("ix_knowledge_nodes_ownership_scope"), table_name="knowledge_nodes")
    op.drop_index(op.f("ix_knowledge_nodes_knowledge_type"), table_name="knowledge_nodes")
    op.drop_index(op.f("ix_knowledge_nodes_title"), table_name="knowledge_nodes")
    op.drop_table("knowledge_nodes")
