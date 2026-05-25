"""Model-level tests for the knowledge graph."""

from __future__ import annotations

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from lms.graphs.models import KnowledgeEdge, KnowledgeNode


def _seed_node(
    session: Session,
    *,
    title: str,
    scope: str,
    knowledge_type: str = "conceptual",
    status: str = "draft",
) -> KnowledgeNode:
    node = KnowledgeNode(
        title=title,
        knowledge_type=knowledge_type,
        ownership_scope=scope,
        status=status,
    )
    session.add(node)
    session.flush()
    return node


def test_knowledge_graph_tables_are_created_by_base_metadata(db_session: Session) -> None:
    """``Base.metadata.create_all`` creates the knowledge graph tables."""
    bind = db_session.bind
    assert bind is not None
    inspector = inspect(bind)
    names = set(inspector.get_table_names())
    assert "knowledge_nodes" in names
    assert "knowledge_edges" in names


def test_normal_edge_cannot_cross_ownership_scope(db_session: Session) -> None:
    """A normal (non-graph-reference) edge cannot link personal to institutional."""
    personal = _seed_node(db_session, title="Personal Origin", scope="personal")
    institutional = _seed_node(db_session, title="Institutional Target", scope="institutional")

    bad_edge = KnowledgeEdge(
        source_node_id=personal.id,
        target_node_id=institutional.id,
        edge_type="prerequisite",
        source_scope="personal",
        target_scope="institutional",
        is_graph_reference=False,
        status="draft",
    )
    db_session.add(bad_edge)
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_cross_scope_edge_allowed_when_marked_as_graph_reference(
    db_session: Session,
) -> None:
    """Cross-scope linkage requires the explicit ``is_graph_reference`` marker."""
    personal = _seed_node(db_session, title="Personal Goal", scope="personal")
    institutional = _seed_node(db_session, title="Institutional Concept", scope="institutional")

    edge = KnowledgeEdge(
        source_node_id=personal.id,
        target_node_id=institutional.id,
        edge_type="prerequisite",
        source_scope="personal",
        target_scope="institutional",
        is_graph_reference=True,
        status="draft",
    )
    db_session.add(edge)
    db_session.flush()
    stored = db_session.get(KnowledgeEdge, edge.id)
    assert stored is not None
    assert stored.is_graph_reference is True
    assert stored.source_scope == "personal"
    assert stored.target_scope == "institutional"


def test_edge_rejects_self_loop(db_session: Session) -> None:
    """An edge cannot point at the same source and target node."""
    node = _seed_node(db_session, title="Loopy", scope="personal")
    db_session.add(
        KnowledgeEdge(
            source_node_id=node.id,
            target_node_id=node.id,
            edge_type="prerequisite",
            source_scope="personal",
            target_scope="personal",
            is_graph_reference=False,
            status="draft",
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_invalid_knowledge_type_rejected_by_check_constraint(
    db_session: Session,
) -> None:
    """Unknown knowledge_type values are rejected at the database layer."""
    db_session.add(
        KnowledgeNode(
            title="Bogus",
            knowledge_type="invalid",
            ownership_scope="personal",
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()
