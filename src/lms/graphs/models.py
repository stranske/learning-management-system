"""SQLAlchemy models for the LMS knowledge graph (Milestone 2)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    String,
    Text,
    false,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from lms.auth.models import new_uuid, utc_now
from lms.db.base import Base

KNOWLEDGE_TYPES: tuple[str, ...] = (
    "factual",
    "conceptual",
    "procedural",
    "judgment",
    "metacognitive",
    "social",
    "compliance",
)
OWNERSHIP_SCOPES: tuple[str, ...] = ("personal", "institutional")
NODE_STATUSES: tuple[str, ...] = ("draft", "published", "deprecated")
NODE_PROVENANCES: tuple[str, ...] = ("manual", "imported", "llm-proposed")
EDGE_TYPES: tuple[str, ...] = (
    "prerequisite",
    "key-prerequisite",
    "encompassing",
    "interference-risk",
    "analogy",
    "contrast",
    "transfer-context",
    "supports-competency",
)
EDGE_STATUSES: tuple[str, ...] = ("draft", "published", "deprecated")


def _sql_values(values: tuple[str, ...]) -> str:
    """Return SQL string literals for a check constraint."""
    return ", ".join(f"'{value}'" for value in values)


class KnowledgeNode(Base):
    """A unit of knowledge that learners can study and acquire evidence against.

    The model is intentionally conservative for v1: prerequisite/encompassing
    edges between published nodes drive the Minimum Demo. Status is gated so
    that draft nodes cannot be referenced by prompts or the scheduler until a
    reviewer publishes them (the publication gate lives in later issues but the
    status column is the contract those checks depend on).
    """

    __tablename__ = "knowledge_nodes"
    __table_args__ = (
        CheckConstraint(
            f"knowledge_type IN ({_sql_values(KNOWLEDGE_TYPES)})",
            name="knowledge_type_valid",
        ),
        CheckConstraint(
            f"ownership_scope IN ({_sql_values(OWNERSHIP_SCOPES)})",
            name="ownership_scope_valid",
        ),
        CheckConstraint(
            f"status IN ({_sql_values(NODE_STATUSES)})",
            name="status_valid",
        ),
        CheckConstraint(
            f"provenance IN ({_sql_values(NODE_PROVENANCES)})",
            name="provenance_valid",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    knowledge_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    ownership_scope: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="draft", server_default="draft", index=True
    )
    provenance: Mapped[str] = mapped_column(
        String(32), nullable=False, default="manual", server_default="manual"
    )
    imported_from: Mapped[str | None] = mapped_column(String(1024))
    source_reference_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("source_references.id", name="fk_knowledge_nodes_source_reference_id"),
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        server_default=func.now(),
        nullable=False,
    )


class KnowledgeEdge(Base):
    """A typed relationship between two ``KnowledgeNode`` records.

    A normal edge cannot cross ownership scopes; cross-scope linkage requires an
    explicit ``is_graph_reference`` marker so that personal evidence does not
    silently flow into institutional analytics (and vice versa). The check
    constraint is the database floor under the repository's explicit-scope
    contract.
    """

    __tablename__ = "knowledge_edges"
    __table_args__ = (
        CheckConstraint(
            f"edge_type IN ({_sql_values(EDGE_TYPES)})",
            name="edge_type_valid",
        ),
        CheckConstraint(
            f"source_scope IN ({_sql_values(OWNERSHIP_SCOPES)})",
            name="source_scope_valid",
        ),
        CheckConstraint(
            f"target_scope IN ({_sql_values(OWNERSHIP_SCOPES)})",
            name="target_scope_valid",
        ),
        CheckConstraint(
            f"status IN ({_sql_values(EDGE_STATUSES)})",
            name="status_valid",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0)",
            name="confidence_unit_interval",
        ),
        CheckConstraint(
            "source_scope = target_scope OR is_graph_reference = 1",
            name="no_cross_scope_normal_edge",
        ),
        CheckConstraint(
            "source_node_id <> target_node_id",
            name="no_self_loop",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    source_node_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("knowledge_nodes.id", name="fk_knowledge_edges_source_node_id"),
        nullable=False,
        index=True,
    )
    target_node_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("knowledge_nodes.id", name="fk_knowledge_edges_target_node_id"),
        nullable=False,
        index=True,
    )
    edge_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="prerequisite", index=True
    )
    source_scope: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    target_scope: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    is_graph_reference: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    confidence: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="draft", server_default="draft", index=True
    )
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        server_default=func.now(),
        nullable=False,
    )
