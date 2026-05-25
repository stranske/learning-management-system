"""SQLAlchemy models for scoped knowledge graph records."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from lms.auth.models import new_uuid, utc_now
from lms.db.base import Base

KNOWLEDGE_TYPES: tuple[str, ...] = ("concept", "fact", "procedure", "principle", "question")
OWNERSHIP_SCOPES: tuple[str, ...] = ("personal", "institutional")
KNOWLEDGE_STATUSES: tuple[str, ...] = ("draft", "published", "archived")
EDGE_TYPES: tuple[str, ...] = ("prerequisite", "supports", "contradicts", "cross-scope-reference")
EDGE_STATUSES: tuple[str, ...] = ("draft", "active", "archived")


def _sql_values(values: tuple[str, ...]) -> str:
    """Return SQL string literals for a check constraint."""
    return ", ".join(f"'{value}'" for value in values)


class KnowledgeNode(Base):
    """A learner-visible concept or claim in a scoped knowledge graph."""

    __tablename__ = "knowledge_nodes"
    __table_args__ = (
        CheckConstraint(
            f"knowledge_type IN ({_sql_values(KNOWLEDGE_TYPES)})",
            name="knowledge_type_valid",
        ),
        CheckConstraint(
            f"ownership_scope IN ({_sql_values(OWNERSHIP_SCOPES)})",
            name="knowledge_node_ownership_scope_valid",
        ),
        CheckConstraint(
            f"status IN ({_sql_values(KNOWLEDGE_STATUSES)})",
            name="knowledge_node_status_valid",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(String(2048))
    knowledge_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    ownership_scope: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False, index=True)
    provenance: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    imported_from: Mapped[str | None] = mapped_column(String(1024))
    source_reference_id: Mapped[str | None] = mapped_column(
        ForeignKey("source_references.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        nullable=False,
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        server_default=func.now(),
        nullable=False,
    )

    outgoing_edges: Mapped[list[KnowledgeEdge]] = relationship(
        "KnowledgeEdge",
        back_populates="source_node",
        cascade="all, delete-orphan",
        foreign_keys="KnowledgeEdge.source_node_id",
    )
    incoming_edges: Mapped[list[KnowledgeEdge]] = relationship(
        "KnowledgeEdge",
        back_populates="target_node",
        cascade="all, delete-orphan",
        foreign_keys="KnowledgeEdge.target_node_id",
    )


class GraphReference(Base):
    """Explicit authorization for a cross-scope graph link."""

    __tablename__ = "graph_references"
    __table_args__ = (
        CheckConstraint(
            f"source_scope IN ({_sql_values(OWNERSHIP_SCOPES)})",
            name="graph_reference_source_scope_valid",
        ),
        CheckConstraint(
            f"target_scope IN ({_sql_values(OWNERSHIP_SCOPES)})",
            name="graph_reference_target_scope_valid",
        ),
        CheckConstraint("source_scope != target_scope", name="graph_reference_cross_scope_only"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    source_scope: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    target_scope: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(String(1024), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        nullable=False,
    )


class KnowledgeEdge(Base):
    """A typed relationship between two knowledge nodes."""

    __tablename__ = "knowledge_edges"
    __table_args__ = (
        CheckConstraint(
            f"edge_type IN ({_sql_values(EDGE_TYPES)})",
            name="knowledge_edge_type_valid",
        ),
        CheckConstraint(
            f"source_scope IN ({_sql_values(OWNERSHIP_SCOPES)})",
            name="knowledge_edge_source_scope_valid",
        ),
        CheckConstraint(
            f"target_scope IN ({_sql_values(OWNERSHIP_SCOPES)})",
            name="knowledge_edge_target_scope_valid",
        ),
        CheckConstraint(
            f"ownership_scope IN ({_sql_values(OWNERSHIP_SCOPES)})",
            name="knowledge_edge_ownership_scope_valid",
        ),
        CheckConstraint(
            f"status IN ({_sql_values(EDGE_STATUSES)})",
            name="knowledge_edge_status_valid",
        ),
        CheckConstraint(
            "source_scope = target_scope OR "
            "(edge_type = 'cross-scope-reference' AND graph_reference_id IS NOT NULL)",
            name="knowledge_edge_cross_scope_requires_reference",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    source_node_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_nodes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_node_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_nodes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    edge_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    ownership_scope: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    source_scope: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    target_scope: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    confidence: Mapped[float | None] = mapped_column()
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False, index=True)
    provenance: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    graph_reference_id: Mapped[str | None] = mapped_column(
        ForeignKey("graph_references.id", ondelete="SET NULL"), index=True
    )
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    updated_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        nullable=False,
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        server_default=func.now(),
        nullable=False,
    )

    source_node: Mapped[KnowledgeNode] = relationship(
        "KnowledgeNode",
        back_populates="outgoing_edges",
        foreign_keys=[source_node_id],
    )
    target_node: Mapped[KnowledgeNode] = relationship(
        "KnowledgeNode",
        back_populates="incoming_edges",
        foreign_keys=[target_node_id],
    )
