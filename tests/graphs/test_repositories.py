"""Knowledge graph repository tests."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from lms.audit.models import AuditLog
from lms.graphs.repository import (
    create_knowledge_edge,
    create_knowledge_node,
    list_knowledge_edges,
    list_knowledge_nodes,
)


def test_node_queries_require_explicit_scope(db_session: Session) -> None:
    """Repository reads reject implicit all-scope queries."""
    create_knowledge_node(
        db_session,
        title="Retrieval practice",
        knowledge_type="concept",
        ownership_scope="personal",
        actor_id="user:alice",
    )

    with pytest.raises(ValueError, match="scope is required"):
        list_knowledge_nodes(db_session, scope=None)


def test_node_queries_filter_to_requested_scope(db_session: Session) -> None:
    """Only nodes in the requested scope are returned."""
    personal = create_knowledge_node(
        db_session,
        title="Personal note",
        knowledge_type="fact",
        ownership_scope="personal",
        actor_id="user:alice",
    )
    create_knowledge_node(
        db_session,
        title="Institutional rubric",
        knowledge_type="principle",
        ownership_scope="institutional",
        actor_id="user:alice",
    )
    db_session.commit()

    assert [node.id for node in list_knowledge_nodes(db_session, scope="personal")] == [personal.id]


def test_edge_queries_require_explicit_scope(db_session: Session) -> None:
    """Edge reads reject implicit all-scope queries."""
    with pytest.raises(ValueError, match="scope is required"):
        list_knowledge_edges(db_session, scope=None)


def test_create_node_and_edge_record_audit_events(db_session: Session) -> None:
    """Graph creates write KnowledgeNode and KnowledgeEdge audit events."""
    source = create_knowledge_node(
        db_session,
        title="Encoding",
        knowledge_type="concept",
        ownership_scope="personal",
        actor_id="user:alice",
    )
    target = create_knowledge_node(
        db_session,
        title="Retrieval",
        knowledge_type="concept",
        ownership_scope="personal",
        actor_id="user:alice",
    )
    edge = create_knowledge_edge(
        db_session,
        source_node_id=source.id,
        target_node_id=target.id,
        edge_type="prerequisite",
        confidence=0.8,
        actor_id="user:alice",
    )
    db_session.commit()

    events = db_session.query(AuditLog).order_by(AuditLog.entity_type, AuditLog.id).all()
    assert [event.entity_type for event in events] == [
        "KnowledgeEdge",
        "KnowledgeNode",
        "KnowledgeNode",
    ]
    assert edge.ownership_scope == "personal"
