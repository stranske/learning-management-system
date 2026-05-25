"""Create knowledge_nodes and knowledge_edges tables.

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
    """Create knowledge graph node and edge tables with scope constraints."""
    op.create_table(
        "knowledge_nodes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("knowledge_type", sa.String(length=32), nullable=False),
        sa.Column("ownership_scope", sa.String(length=32), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="draft",
        ),
        sa.Column(
            "provenance",
            sa.String(length=32),
            nullable=False,
            server_default="manual",
        ),
        sa.Column("imported_from", sa.String(length=1024), nullable=True),
        sa.Column("source_reference_id", sa.String(length=36), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "knowledge_type IN ('factual', 'conceptual', 'procedural', 'judgment', "
            "'metacognitive', 'social', 'compliance')",
            name=op.f("ck_knowledge_nodes_knowledge_type_valid"),
        ),
        sa.CheckConstraint(
            "ownership_scope IN ('personal', 'institutional')",
            name=op.f("ck_knowledge_nodes_ownership_scope_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'published', 'deprecated')",
            name=op.f("ck_knowledge_nodes_status_valid"),
        ),
        sa.CheckConstraint(
            "provenance IN ('manual', 'imported', 'llm-proposed')",
            name=op.f("ck_knowledge_nodes_provenance_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["source_reference_id"],
            ["source_references.id"],
            name="fk_knowledge_nodes_source_reference_id",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_knowledge_nodes")),
    )
    op.create_index(op.f("ix_knowledge_nodes_title"), "knowledge_nodes", ["title"])
    op.create_index(
        op.f("ix_knowledge_nodes_knowledge_type"), "knowledge_nodes", ["knowledge_type"]
    )
    op.create_index(
        op.f("ix_knowledge_nodes_ownership_scope"),
        "knowledge_nodes",
        ["ownership_scope"],
    )
    op.create_index(op.f("ix_knowledge_nodes_status"), "knowledge_nodes", ["status"])
    op.create_index(
        op.f("ix_knowledge_nodes_source_reference_id"),
        "knowledge_nodes",
        ["source_reference_id"],
    )

    op.create_table(
        "knowledge_edges",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("source_node_id", sa.String(length=36), nullable=False),
        sa.Column("target_node_id", sa.String(length=36), nullable=False),
        sa.Column("edge_type", sa.String(length=32), nullable=False),
        sa.Column("source_scope", sa.String(length=32), nullable=False),
        sa.Column("target_scope", sa.String(length=32), nullable=False),
        sa.Column(
            "is_graph_reference",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "edge_type IN ('prerequisite', 'key-prerequisite', 'encompassing', "
            "'interference-risk', 'analogy', 'contrast', 'transfer-context', "
            "'supports-competency')",
            name=op.f("ck_knowledge_edges_edge_type_valid"),
        ),
        sa.CheckConstraint(
            "source_scope IN ('personal', 'institutional')",
            name=op.f("ck_knowledge_edges_source_scope_valid"),
        ),
        sa.CheckConstraint(
            "target_scope IN ('personal', 'institutional')",
            name=op.f("ck_knowledge_edges_target_scope_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'published', 'deprecated')",
            name=op.f("ck_knowledge_edges_status_valid"),
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0)",
            name=op.f("ck_knowledge_edges_confidence_unit_interval"),
        ),
        sa.CheckConstraint(
            "source_scope = target_scope OR is_graph_reference",
            name=op.f("ck_knowledge_edges_no_cross_scope_normal_edge"),
        ),
        sa.CheckConstraint(
            "source_node_id <> target_node_id",
            name=op.f("ck_knowledge_edges_no_self_loop"),
        ),
        sa.ForeignKeyConstraint(
            ["source_node_id"],
            ["knowledge_nodes.id"],
            name="fk_knowledge_edges_source_node_id",
        ),
        sa.ForeignKeyConstraint(
            ["target_node_id"],
            ["knowledge_nodes.id"],
            name="fk_knowledge_edges_target_node_id",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_knowledge_edges")),
    )
    op.create_index(
        op.f("ix_knowledge_edges_source_node_id"),
        "knowledge_edges",
        ["source_node_id"],
    )
    op.create_index(
        op.f("ix_knowledge_edges_target_node_id"),
        "knowledge_edges",
        ["target_node_id"],
    )
    op.create_index(op.f("ix_knowledge_edges_edge_type"), "knowledge_edges", ["edge_type"])
    op.create_index(op.f("ix_knowledge_edges_source_scope"), "knowledge_edges", ["source_scope"])
    op.create_index(op.f("ix_knowledge_edges_target_scope"), "knowledge_edges", ["target_scope"])
    op.create_index(op.f("ix_knowledge_edges_status"), "knowledge_edges", ["status"])


def downgrade() -> None:
    """Drop knowledge graph tables and indexes."""
    op.drop_index(op.f("ix_knowledge_edges_status"), table_name="knowledge_edges")
    op.drop_index(op.f("ix_knowledge_edges_target_scope"), table_name="knowledge_edges")
    op.drop_index(op.f("ix_knowledge_edges_source_scope"), table_name="knowledge_edges")
    op.drop_index(op.f("ix_knowledge_edges_edge_type"), table_name="knowledge_edges")
    op.drop_index(op.f("ix_knowledge_edges_target_node_id"), table_name="knowledge_edges")
    op.drop_index(op.f("ix_knowledge_edges_source_node_id"), table_name="knowledge_edges")
    op.drop_table("knowledge_edges")

    op.drop_index(op.f("ix_knowledge_nodes_source_reference_id"), table_name="knowledge_nodes")
    op.drop_index(op.f("ix_knowledge_nodes_status"), table_name="knowledge_nodes")
    op.drop_index(op.f("ix_knowledge_nodes_ownership_scope"), table_name="knowledge_nodes")
    op.drop_index(op.f("ix_knowledge_nodes_knowledge_type"), table_name="knowledge_nodes")
    op.drop_index(op.f("ix_knowledge_nodes_title"), table_name="knowledge_nodes")
    op.drop_table("knowledge_nodes")
