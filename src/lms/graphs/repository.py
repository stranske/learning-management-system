"""Repository helpers for scoped knowledge graph CRUD."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from lms.audit.repository import record_audit_event
from lms.graphs.models import GraphReference, KnowledgeEdge, KnowledgeNode


def create_knowledge_node(
    session: Session,
    *,
    title: str,
    knowledge_type: str,
    ownership_scope: str,
    actor_id: str,
    description: str | None = None,
    status: str = "draft",
    provenance: Mapping[str, Any] | None = None,
    imported_from: str | None = None,
    source_reference_id: str | None = None,
    source_subsystem: str = "api",
) -> KnowledgeNode:
    """Create one scoped node and record an audit event."""
    node = KnowledgeNode(
        title=title,
        description=description,
        knowledge_type=knowledge_type,
        ownership_scope=ownership_scope,
        status=status,
        provenance=dict(provenance) if provenance is not None else None,
        imported_from=imported_from,
        source_reference_id=source_reference_id,
    )
    session.add(node)
    session.flush()
    record_audit_event(
        session,
        actor_id=actor_id,
        action="create",
        entity_type="KnowledgeNode",
        entity_id=node.id,
        source_subsystem=source_subsystem,
        after_summary=_node_summary(node),
    )
    return node


def get_knowledge_node(session: Session, node_id: str) -> KnowledgeNode | None:
    """Return a knowledge node by id."""
    return session.get(KnowledgeNode, node_id)


def list_knowledge_nodes(
    session: Session,
    *,
    scope: str | None,
    status: str | None = None,
    limit: int = 100,
) -> Sequence[KnowledgeNode]:
    """List nodes for an explicit ownership scope.

    Callers must choose the scope they are reading. This prevents accidental
    all-scope graph queries from leaking personal and institutional records
    into the same result set.
    """
    if scope is None:
        raise ValueError("scope is required for knowledge node queries")
    statement = select(KnowledgeNode).where(KnowledgeNode.ownership_scope == scope)
    if status is not None:
        statement = statement.where(KnowledgeNode.status == status)
    statement = statement.order_by(KnowledgeNode.created_at.desc(), KnowledgeNode.id).limit(limit)
    return list(session.scalars(statement))


def create_graph_reference(
    session: Session,
    *,
    source_scope: str,
    target_scope: str,
    reason: str,
    actor_id: str,
) -> GraphReference:
    """Create an explicit cross-scope reference authorization."""
    reference = GraphReference(
        source_scope=source_scope,
        target_scope=target_scope,
        reason=reason,
        actor_id=actor_id,
    )
    session.add(reference)
    session.flush()
    return reference


def create_knowledge_edge(
    session: Session,
    *,
    source_node_id: str,
    target_node_id: str,
    edge_type: str,
    actor_id: str,
    confidence: float | None = None,
    status: str = "draft",
    provenance: Mapping[str, Any] | None = None,
    graph_reference_id: str | None = None,
    source_subsystem: str = "api",
) -> KnowledgeEdge:
    """Create an edge after deriving endpoint scopes from the stored nodes."""
    source = get_knowledge_node(session, source_node_id)
    target = get_knowledge_node(session, target_node_id)
    if source is None or target is None:
        raise ValueError("source and target knowledge nodes must exist")
    edge = KnowledgeEdge(
        source_node_id=source.id,
        target_node_id=target.id,
        edge_type=edge_type,
        ownership_scope=source.ownership_scope,
        source_scope=source.ownership_scope,
        target_scope=target.ownership_scope,
        confidence=confidence,
        status=status,
        provenance=dict(provenance) if provenance is not None else None,
        graph_reference_id=graph_reference_id,
        created_by=actor_id,
        updated_by=actor_id,
    )
    session.add(edge)
    session.flush()
    record_audit_event(
        session,
        actor_id=actor_id,
        action="create",
        entity_type="KnowledgeEdge",
        entity_id=edge.id,
        source_subsystem=source_subsystem,
        after_summary=_edge_summary(edge),
    )
    return edge


def get_knowledge_edge(session: Session, edge_id: str) -> KnowledgeEdge | None:
    """Return a knowledge edge by id."""
    return session.get(KnowledgeEdge, edge_id)


def list_knowledge_edges(
    session: Session,
    *,
    scope: str | None,
    status: str | None = None,
    limit: int = 100,
) -> Sequence[KnowledgeEdge]:
    """List edges for an explicit ownership scope."""
    if scope is None:
        raise ValueError("scope is required for knowledge edge queries")
    statement = select(KnowledgeEdge).where(KnowledgeEdge.ownership_scope == scope)
    if status is not None:
        statement = statement.where(KnowledgeEdge.status == status)
    statement = statement.order_by(KnowledgeEdge.created_at.desc(), KnowledgeEdge.id).limit(limit)
    return list(session.scalars(statement))


def _node_summary(node: KnowledgeNode) -> dict[str, Any]:
    return {
        "id": node.id,
        "title": node.title,
        "knowledge_type": node.knowledge_type,
        "ownership_scope": node.ownership_scope,
        "status": node.status,
        "source_reference_id": node.source_reference_id,
    }


def _edge_summary(edge: KnowledgeEdge) -> dict[str, Any]:
    return {
        "id": edge.id,
        "source_node_id": edge.source_node_id,
        "target_node_id": edge.target_node_id,
        "edge_type": edge.edge_type,
        "ownership_scope": edge.ownership_scope,
        "source_scope": edge.source_scope,
        "target_scope": edge.target_scope,
        "status": edge.status,
        "graph_reference_id": edge.graph_reference_id,
    }
