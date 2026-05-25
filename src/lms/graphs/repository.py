"""Repository helpers for KnowledgeNode and KnowledgeEdge CRUD.

All node and edge queries require an explicit ``scope`` argument so the
ownership boundary is enforced at the data-access layer (the database
check constraint on edges is the floor under this policy). Aggregating
across scopes must use the explicit ``list_knowledge_nodes_across_scopes``
helper, which returns scope-tagged rows.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from lms.audit.repository import record_audit_event
from lms.graphs.models import (
    EDGE_STATUSES,
    EDGE_TYPES,
    KNOWLEDGE_TYPES,
    NODE_PROVENANCES,
    NODE_STATUSES,
    OWNERSHIP_SCOPES,
    KnowledgeEdge,
    KnowledgeNode,
)


def _require_scope(scope: str | None) -> str:
    """Validate that callers pass an explicit ownership scope."""
    if scope is None:
        raise ValueError(
            "ownership scope is required; pass scope='personal' or 'institutional' "
            "explicitly. Use list_knowledge_nodes_across_scopes for scope-aggregating "
            "reads."
        )
    if scope not in OWNERSHIP_SCOPES:
        raise ValueError(f"unknown ownership scope {scope!r}; expected one of {OWNERSHIP_SCOPES}")
    return scope


def _require_choice(value: str, allowed: tuple[str, ...], label: str) -> str:
    if value not in allowed:
        raise ValueError(f"unknown {label} {value!r}; expected one of {allowed}")
    return value


def create_knowledge_node(
    session: Session,
    *,
    title: str,
    knowledge_type: str,
    scope: str,
    actor_id: str,
    description: str | None = None,
    status: str = "draft",
    provenance: str = "manual",
    imported_from: str | None = None,
    source_reference_id: str | None = None,
    source_subsystem: str = "api",
) -> KnowledgeNode:
    """Create a knowledge node within an explicit ownership scope."""
    _require_scope(scope)
    _require_choice(knowledge_type, KNOWLEDGE_TYPES, "knowledge type")
    _require_choice(status, NODE_STATUSES, "status")
    _require_choice(provenance, NODE_PROVENANCES, "provenance")

    node = KnowledgeNode(
        title=title,
        description=description,
        knowledge_type=knowledge_type,
        ownership_scope=scope,
        status=status,
        provenance=provenance,
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


def get_knowledge_node(session: Session, node_id: str, *, scope: str) -> KnowledgeNode | None:
    """Return a node by id only if it belongs to the requested scope."""
    _require_scope(scope)
    node = session.get(KnowledgeNode, node_id)
    if node is None or node.ownership_scope != scope:
        return None
    return node


def get_knowledge_node_for_prompt_creation(
    session: Session,
    node_id: str,
    *,
    scope: str,
) -> KnowledgeNode | None:
    """Return a node only when it is eligible for prompt creation.

    Prompt creation is intentionally restricted to published nodes so imported
    draft notes cannot be consumed until later authoring/publish workflow marks
    them ready.
    """
    node = get_knowledge_node(session, node_id, scope=scope)
    if node is None or node.status != "published":
        return None
    return node


def list_knowledge_nodes(
    session: Session,
    *,
    scope: str,
    status: str | None = None,
    knowledge_type: str | None = None,
    limit: int = 100,
) -> Sequence[KnowledgeNode]:
    """List nodes within one ownership scope."""
    _require_scope(scope)
    statement = select(KnowledgeNode).where(KnowledgeNode.ownership_scope == scope)
    if status is not None:
        _require_choice(status, NODE_STATUSES, "status")
        statement = statement.where(KnowledgeNode.status == status)
    if knowledge_type is not None:
        _require_choice(knowledge_type, KNOWLEDGE_TYPES, "knowledge type")
        statement = statement.where(KnowledgeNode.knowledge_type == knowledge_type)
    statement = statement.order_by(KnowledgeNode.created_at.desc(), KnowledgeNode.id).limit(limit)
    return list(session.scalars(statement))


def list_knowledge_nodes_across_scopes(
    session: Session,
    *,
    limit: int = 100,
) -> Sequence[KnowledgeNode]:
    """Explicit aggregation across ownership scopes.

    Callers that legitimately need cross-scope visibility (admin tooling, fleet
    health reports) must opt in by name. The repository's normal CRUD helpers
    refuse implicit cross-scope reads to keep personal and institutional data
    separate by default.
    """
    statement = (
        select(KnowledgeNode)
        .order_by(KnowledgeNode.created_at.desc(), KnowledgeNode.id)
        .limit(limit)
    )
    return list(session.scalars(statement))


def update_knowledge_node(
    session: Session,
    node: KnowledgeNode,
    *,
    actor_id: str,
    source_subsystem: str = "api",
    **changes: Any,
) -> KnowledgeNode:
    """Update mutable node fields and record one audit event."""
    if "ownership_scope" in changes:
        raise ValueError("ownership_scope is immutable on KnowledgeNode")
    before = _node_summary(node)
    for field, value in changes.items():
        if value is None:
            continue
        if field == "knowledge_type":
            _require_choice(value, KNOWLEDGE_TYPES, "knowledge type")
        elif field == "status":
            _require_choice(value, NODE_STATUSES, "status")
        elif field == "provenance":
            _require_choice(value, NODE_PROVENANCES, "provenance")
        setattr(node, field, value)
    session.flush()
    record_audit_event(
        session,
        actor_id=actor_id,
        action="update",
        entity_type="KnowledgeNode",
        entity_id=node.id,
        source_subsystem=source_subsystem,
        before_summary=before,
        after_summary=_node_summary(node),
    )
    return node


def delete_knowledge_node(
    session: Session,
    node: KnowledgeNode,
    *,
    actor_id: str,
    source_subsystem: str = "api",
) -> None:
    """Delete a node and record the authoring audit event."""
    before = _node_summary(node)
    node_id = node.id
    session.delete(node)
    session.flush()
    record_audit_event(
        session,
        actor_id=actor_id,
        action="delete",
        entity_type="KnowledgeNode",
        entity_id=node_id,
        source_subsystem=source_subsystem,
        before_summary=before,
    )


def create_knowledge_edge(
    session: Session,
    *,
    source_node_id: str,
    target_node_id: str,
    edge_type: str,
    scope: str,
    actor_id: str,
    target_scope: str | None = None,
    is_graph_reference: bool = False,
    confidence: float | None = None,
    status: str = "draft",
    notes: str | None = None,
    source_subsystem: str = "api",
) -> KnowledgeEdge:
    """Create a typed edge between two nodes within an ownership scope.

    ``scope`` is the source-side scope. ``target_scope`` defaults to the same
    value, matching the v1 expectation that edges stay within one scope. To
    create a cross-scope link, callers must pass ``is_graph_reference=True``.
    The explicit flag documents the boundary crossing, and the database
    constraint refuses any other cross-scope edge.
    """
    _require_scope(scope)
    if target_scope is None:
        target_scope = scope
    _require_scope(target_scope)
    _require_choice(edge_type, EDGE_TYPES, "edge type")
    _require_choice(status, EDGE_STATUSES, "status")

    if source_node_id == target_node_id:
        raise ValueError("knowledge edge cannot point to its own source node")
    if scope != target_scope and not is_graph_reference:
        raise ValueError(
            "cross-scope edges require is_graph_reference=True for "
            "personal/institutional linkage"
        )
    if confidence is not None and not 0.0 <= confidence <= 1.0:
        raise ValueError("confidence must be between 0.0 and 1.0 (inclusive)")

    source_node = session.get(KnowledgeNode, source_node_id)
    target_node = session.get(KnowledgeNode, target_node_id)
    if source_node is None or target_node is None:
        raise ValueError("source and target nodes must exist before creating an edge")
    if source_node.ownership_scope != scope:
        raise ValueError(
            f"source node scope {source_node.ownership_scope!r} does not match "
            f"requested edge scope {scope!r}"
        )
    if target_node.ownership_scope != target_scope:
        raise ValueError(
            f"target node scope {target_node.ownership_scope!r} does not match "
            f"requested target_scope {target_scope!r}"
        )

    edge = KnowledgeEdge(
        source_node_id=source_node_id,
        target_node_id=target_node_id,
        edge_type=edge_type,
        source_scope=scope,
        target_scope=target_scope,
        is_graph_reference=is_graph_reference,
        confidence=confidence,
        status=status,
        notes=notes,
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


def get_knowledge_edge(session: Session, edge_id: str, *, scope: str) -> KnowledgeEdge | None:
    """Return an edge by id only if its source scope matches the requested scope."""
    _require_scope(scope)
    edge = session.get(KnowledgeEdge, edge_id)
    if edge is None or edge.source_scope != scope:
        return None
    return edge


def list_knowledge_edges(
    session: Session,
    *,
    scope: str,
    edge_type: str | None = None,
    status: str | None = None,
    source_node_id: str | None = None,
    target_node_id: str | None = None,
    limit: int = 100,
) -> Sequence[KnowledgeEdge]:
    """List edges anchored on one source-side ownership scope."""
    _require_scope(scope)
    statement = select(KnowledgeEdge).where(KnowledgeEdge.source_scope == scope)
    if edge_type is not None:
        _require_choice(edge_type, EDGE_TYPES, "edge type")
        statement = statement.where(KnowledgeEdge.edge_type == edge_type)
    if status is not None:
        _require_choice(status, EDGE_STATUSES, "status")
        statement = statement.where(KnowledgeEdge.status == status)
    if source_node_id is not None:
        statement = statement.where(KnowledgeEdge.source_node_id == source_node_id)
    if target_node_id is not None:
        statement = statement.where(KnowledgeEdge.target_node_id == target_node_id)
    statement = statement.order_by(KnowledgeEdge.created_at.desc(), KnowledgeEdge.id).limit(limit)
    return list(session.scalars(statement))


def delete_knowledge_edge(
    session: Session,
    edge: KnowledgeEdge,
    *,
    actor_id: str,
    source_subsystem: str = "api",
) -> None:
    """Delete an edge and record the authoring audit event."""
    before = _edge_summary(edge)
    edge_id = edge.id
    session.delete(edge)
    session.flush()
    record_audit_event(
        session,
        actor_id=actor_id,
        action="delete",
        entity_type="KnowledgeEdge",
        entity_id=edge_id,
        source_subsystem=source_subsystem,
        before_summary=before,
    )


def _node_summary(node: KnowledgeNode) -> Mapping[str, Any]:
    return {
        "id": node.id,
        "title": node.title,
        "knowledge_type": node.knowledge_type,
        "ownership_scope": node.ownership_scope,
        "status": node.status,
        "provenance": node.provenance,
        "imported_from": node.imported_from,
        "source_reference_id": node.source_reference_id,
    }


def _edge_summary(edge: KnowledgeEdge) -> Mapping[str, Any]:
    return {
        "id": edge.id,
        "source_node_id": edge.source_node_id,
        "target_node_id": edge.target_node_id,
        "edge_type": edge.edge_type,
        "source_scope": edge.source_scope,
        "target_scope": edge.target_scope,
        "is_graph_reference": edge.is_graph_reference,
        "confidence": edge.confidence,
        "status": edge.status,
    }
