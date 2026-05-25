"""Repository-level tests for the knowledge graph."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from lms.audit.models import AuditLog
from lms.graphs.repository import (
    create_knowledge_edge,
    create_knowledge_node,
    get_knowledge_node,
    list_knowledge_edges,
    list_knowledge_nodes,
    list_knowledge_nodes_across_scopes,
)


def _seed_pair(
    session: Session,
    *,
    scope: str = "personal",
) -> tuple[str, str]:
    parent = create_knowledge_node(
        session,
        title=f"{scope.title()} Parent",
        knowledge_type="conceptual",
        scope=scope,
        actor_id="user:alice",
    )
    child = create_knowledge_node(
        session,
        title=f"{scope.title()} Child",
        knowledge_type="conceptual",
        scope=scope,
        actor_id="user:alice",
    )
    session.commit()
    return parent.id, child.id


def test_node_queries_require_explicit_scope(db_session: Session) -> None:
    """``list_knowledge_nodes`` refuses implicit all-scope reads.

    The repository contract is that every CRUD call passes an explicit ``scope``
    argument. Calls without it raise ``ValueError`` so accidental cross-scope
    reads cannot ship; aggregation must use
    ``list_knowledge_nodes_across_scopes`` by name.
    """
    create_knowledge_node(
        db_session,
        title="Scoped node",
        knowledge_type="factual",
        scope="personal",
        actor_id="user:alice",
    )
    db_session.commit()

    with pytest.raises(ValueError):
        list_knowledge_nodes(db_session, scope=None)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        get_knowledge_node(db_session, "any-id", scope=None)  # type: ignore[arg-type]


def test_list_knowledge_nodes_returns_only_requested_scope(db_session: Session) -> None:
    """Personal and institutional rows do not bleed into each other."""
    create_knowledge_node(
        db_session,
        title="Personal",
        knowledge_type="factual",
        scope="personal",
        actor_id="user:alice",
    )
    create_knowledge_node(
        db_session,
        title="Institutional",
        knowledge_type="factual",
        scope="institutional",
        actor_id="user:alice",
    )
    db_session.commit()

    personal = list_knowledge_nodes(db_session, scope="personal")
    institutional = list_knowledge_nodes(db_session, scope="institutional")
    aggregated = list_knowledge_nodes_across_scopes(db_session)

    assert [node.title for node in personal] == ["Personal"]
    assert [node.title for node in institutional] == ["Institutional"]
    assert len(aggregated) == 2


def test_create_node_writes_audit_event(db_session: Session) -> None:
    """Creating a node records a KnowledgeNode audit event."""
    node = create_knowledge_node(
        db_session,
        title="Audit me",
        knowledge_type="procedural",
        scope="personal",
        actor_id="user:alice",
    )
    db_session.commit()

    audit = db_session.query(AuditLog).filter_by(entity_id=node.id).one()
    assert audit.entity_type == "KnowledgeNode"
    assert audit.action == "create"
    assert audit.after_summary is not None
    assert audit.after_summary["ownership_scope"] == "personal"


def test_create_edge_rejects_implicit_cross_scope(db_session: Session) -> None:
    """Creating an edge across scopes without is_graph_reference fails fast."""
    personal_parent, _ = _seed_pair(db_session, scope="personal")
    institutional_parent, _ = _seed_pair(db_session, scope="institutional")

    with pytest.raises(ValueError):
        create_knowledge_edge(
            db_session,
            source_node_id=personal_parent,
            target_node_id=institutional_parent,
            edge_type="prerequisite",
            scope="personal",
            target_scope="institutional",
            is_graph_reference=False,
            actor_id="user:alice",
        )


def test_create_edge_rejects_scope_mismatch_with_node(db_session: Session) -> None:
    """An edge's declared scope must match the underlying nodes' scopes."""
    personal_parent, personal_child = _seed_pair(db_session, scope="personal")

    with pytest.raises(ValueError):
        create_knowledge_edge(
            db_session,
            source_node_id=personal_parent,
            target_node_id=personal_child,
            edge_type="prerequisite",
            scope="institutional",
            actor_id="user:alice",
        )


def test_create_prerequisite_edge_creates_audit_event(db_session: Session) -> None:
    """Creating a normal prerequisite edge records a KnowledgeEdge audit event."""
    parent_id, child_id = _seed_pair(db_session, scope="personal")
    edge = create_knowledge_edge(
        db_session,
        source_node_id=parent_id,
        target_node_id=child_id,
        edge_type="prerequisite",
        scope="personal",
        actor_id="user:alice",
    )
    db_session.commit()

    audit = db_session.query(AuditLog).filter_by(entity_id=edge.id).one()
    assert audit.entity_type == "KnowledgeEdge"
    assert audit.action == "create"
    assert audit.after_summary is not None
    assert audit.after_summary["edge_type"] == "prerequisite"
    assert audit.after_summary["source_scope"] == "personal"

    edges = list_knowledge_edges(db_session, scope="personal")
    assert [edge.id for edge in edges] == [edge.id for edge in edges]
    assert all(edge.source_scope == "personal" for edge in edges)
