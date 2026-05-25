"""Repository-level tests for the knowledge graph."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from lms.audit.models import AuditLog
from lms.graphs.repository import (
    create_knowledge_edge,
    create_knowledge_node,
    delete_knowledge_edge,
    delete_knowledge_node,
    get_knowledge_edge,
    get_knowledge_node,
    list_knowledge_edges,
    list_knowledge_nodes,
    list_knowledge_nodes_across_scopes,
    update_knowledge_node,
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
    assert len(edges) == 1
    assert edges[0].id == edge.id
    assert all(edge.source_scope == "personal" for edge in edges)


def test_require_scope_rejects_unknown_value(db_session: Session) -> None:
    """``_require_scope`` rejects unrecognised scope strings."""
    with pytest.raises(ValueError, match="unknown ownership scope"):
        list_knowledge_nodes(db_session, scope="alien")


def test_require_choice_rejects_unknown_knowledge_type(db_session: Session) -> None:
    """``create_knowledge_node`` validates knowledge_type via ``_require_choice``."""
    with pytest.raises(ValueError, match="unknown knowledge type"):
        create_knowledge_node(
            db_session,
            title="Bad type",
            knowledge_type="unknown_type",
            scope="personal",
            actor_id="user:alice",
        )


def test_get_knowledge_node_returns_none_when_not_found(db_session: Session) -> None:
    """``get_knowledge_node`` returns None for a missing id."""
    result = get_knowledge_node(db_session, "does-not-exist", scope="personal")
    assert result is None


def test_get_knowledge_node_returns_none_for_wrong_scope(db_session: Session) -> None:
    """``get_knowledge_node`` returns None when the node belongs to a different scope."""
    node = create_knowledge_node(
        db_session,
        title="Institutional",
        knowledge_type="factual",
        scope="institutional",
        actor_id="user:alice",
    )
    db_session.commit()
    result = get_knowledge_node(db_session, node.id, scope="personal")
    assert result is None


def test_list_knowledge_nodes_with_status_filter(db_session: Session) -> None:
    """``list_knowledge_nodes`` filters by status when provided."""
    create_knowledge_node(
        db_session, title="Draft", knowledge_type="factual", scope="personal", actor_id="u:a"
    )
    node = create_knowledge_node(
        db_session,
        title="Published",
        knowledge_type="factual",
        scope="personal",
        actor_id="u:a",
        status="published",
    )
    db_session.commit()

    results = list_knowledge_nodes(db_session, scope="personal", status="published")
    assert len(results) == 1
    assert results[0].id == node.id


def test_list_knowledge_nodes_with_type_filter(db_session: Session) -> None:
    """``list_knowledge_nodes`` filters by knowledge_type when provided."""
    create_knowledge_node(
        db_session, title="Factual", knowledge_type="factual", scope="personal", actor_id="u:a"
    )
    node = create_knowledge_node(
        db_session,
        title="Procedural",
        knowledge_type="procedural",
        scope="personal",
        actor_id="u:a",
    )
    db_session.commit()

    results = list_knowledge_nodes(db_session, scope="personal", knowledge_type="procedural")
    assert len(results) == 1
    assert results[0].id == node.id


def test_update_knowledge_node_changes_mutable_fields(db_session: Session) -> None:
    """``update_knowledge_node`` persists field changes and records an audit event."""
    node = create_knowledge_node(
        db_session,
        title="Original",
        knowledge_type="factual",
        scope="personal",
        actor_id="u:a",
    )
    db_session.commit()

    updated = update_knowledge_node(
        db_session,
        node,
        actor_id="u:a",
        title="Updated",
        status="published",
    )
    db_session.commit()

    assert updated.title == "Updated"
    assert updated.status == "published"

    audits = db_session.query(AuditLog).filter_by(entity_id=node.id).all()
    actions = {a.action for a in audits}
    assert "update" in actions


def test_update_knowledge_node_rejects_scope_change(db_session: Session) -> None:
    """``update_knowledge_node`` raises if caller tries to change ownership_scope."""
    node = create_knowledge_node(
        db_session,
        title="Locked scope",
        knowledge_type="factual",
        scope="personal",
        actor_id="u:a",
    )
    db_session.commit()

    with pytest.raises(ValueError, match="ownership_scope is immutable"):
        update_knowledge_node(db_session, node, actor_id="u:a", ownership_scope="institutional")


def test_delete_knowledge_node_removes_row_and_audits(db_session: Session) -> None:
    """``delete_knowledge_node`` removes the row and records a delete audit event."""
    node = create_knowledge_node(
        db_session,
        title="To delete",
        knowledge_type="factual",
        scope="personal",
        actor_id="u:a",
    )
    db_session.commit()
    node_id = node.id

    delete_knowledge_node(db_session, node, actor_id="u:a")
    db_session.commit()

    assert get_knowledge_node(db_session, node_id, scope="personal") is None
    audit = db_session.query(AuditLog).filter_by(entity_id=node_id, action="delete").one()
    assert audit.entity_type == "KnowledgeNode"


def test_create_edge_rejects_self_loop(db_session: Session) -> None:
    """``create_knowledge_edge`` raises when source and target are the same node."""
    parent_id, _ = _seed_pair(db_session)
    with pytest.raises(ValueError, match="cannot point to its own source"):
        create_knowledge_edge(
            db_session,
            source_node_id=parent_id,
            target_node_id=parent_id,
            edge_type="prerequisite",
            scope="personal",
            actor_id="u:a",
        )


def test_create_edge_rejects_out_of_range_confidence(db_session: Session) -> None:
    """``create_knowledge_edge`` raises when confidence is outside [0, 1]."""
    parent_id, child_id = _seed_pair(db_session)
    with pytest.raises(ValueError, match="confidence"):
        create_knowledge_edge(
            db_session,
            source_node_id=parent_id,
            target_node_id=child_id,
            edge_type="prerequisite",
            scope="personal",
            actor_id="u:a",
            confidence=1.5,
        )


def test_create_edge_rejects_missing_nodes(db_session: Session) -> None:
    """``create_knowledge_edge`` raises when nodes do not exist."""
    with pytest.raises(ValueError, match="must exist"):
        create_knowledge_edge(
            db_session,
            source_node_id="ghost-1",
            target_node_id="ghost-2",
            edge_type="prerequisite",
            scope="personal",
            actor_id="u:a",
        )


def test_create_edge_rejects_target_scope_mismatch(db_session: Session) -> None:
    """``create_knowledge_edge`` raises when the target node's scope mismatches target_scope."""
    personal_parent, _ = _seed_pair(db_session, scope="personal")
    institutional_parent, _ = _seed_pair(db_session, scope="institutional")

    with pytest.raises(ValueError, match="target node scope"):
        create_knowledge_edge(
            db_session,
            source_node_id=personal_parent,
            target_node_id=institutional_parent,
            edge_type="prerequisite",
            scope="personal",
            target_scope="personal",
            is_graph_reference=True,
            actor_id="u:a",
        )


def test_get_knowledge_edge_returns_none_when_not_found(db_session: Session) -> None:
    """``get_knowledge_edge`` returns None for a missing id."""
    result = get_knowledge_edge(db_session, "does-not-exist", scope="personal")
    assert result is None


def test_get_knowledge_edge_returns_none_for_wrong_scope(db_session: Session) -> None:
    """``get_knowledge_edge`` returns None when the edge belongs to a different scope."""
    parent_id, child_id = _seed_pair(db_session, scope="institutional")
    edge = create_knowledge_edge(
        db_session,
        source_node_id=parent_id,
        target_node_id=child_id,
        edge_type="prerequisite",
        scope="institutional",
        actor_id="u:a",
    )
    db_session.commit()
    result = get_knowledge_edge(db_session, edge.id, scope="personal")
    assert result is None


def test_list_knowledge_edges_with_edge_type_filter(db_session: Session) -> None:
    """``list_knowledge_edges`` filters by edge_type when provided."""
    parent_id, child_id = _seed_pair(db_session)
    create_knowledge_edge(
        db_session,
        source_node_id=parent_id,
        target_node_id=child_id,
        edge_type="prerequisite",
        scope="personal",
        actor_id="u:a",
    )
    db_session.commit()

    results = list_knowledge_edges(db_session, scope="personal", edge_type="prerequisite")
    assert len(results) == 1

    empty = list_knowledge_edges(db_session, scope="personal", edge_type="analogy")
    assert len(empty) == 0


def test_list_knowledge_edges_with_status_filter(db_session: Session) -> None:
    """``list_knowledge_edges`` filters by status when provided."""
    parent_id, child_id = _seed_pair(db_session)
    edge = create_knowledge_edge(
        db_session,
        source_node_id=parent_id,
        target_node_id=child_id,
        edge_type="prerequisite",
        scope="personal",
        actor_id="u:a",
        status="published",
    )
    db_session.commit()

    results = list_knowledge_edges(db_session, scope="personal", status="published")
    assert len(results) == 1
    assert results[0].id == edge.id

    empty = list_knowledge_edges(db_session, scope="personal", status="deprecated")
    assert len(empty) == 0


def test_list_knowledge_edges_with_source_node_filter(db_session: Session) -> None:
    """``list_knowledge_edges`` filters by source_node_id when provided."""
    parent_id, child_id = _seed_pair(db_session)
    edge = create_knowledge_edge(
        db_session,
        source_node_id=parent_id,
        target_node_id=child_id,
        edge_type="prerequisite",
        scope="personal",
        actor_id="u:a",
    )
    db_session.commit()

    results = list_knowledge_edges(db_session, scope="personal", source_node_id=parent_id)
    assert len(results) == 1
    assert results[0].id == edge.id

    empty = list_knowledge_edges(db_session, scope="personal", source_node_id=child_id)
    assert len(empty) == 0


def test_list_knowledge_edges_with_target_node_filter(db_session: Session) -> None:
    """``list_knowledge_edges`` filters by target_node_id when provided."""
    parent_id, child_id = _seed_pair(db_session)
    edge = create_knowledge_edge(
        db_session,
        source_node_id=parent_id,
        target_node_id=child_id,
        edge_type="prerequisite",
        scope="personal",
        actor_id="u:a",
    )
    db_session.commit()

    results = list_knowledge_edges(db_session, scope="personal", target_node_id=child_id)
    assert len(results) == 1
    assert results[0].id == edge.id

    empty = list_knowledge_edges(db_session, scope="personal", target_node_id=parent_id)
    assert len(empty) == 0


def test_delete_knowledge_edge_removes_row_and_audits(db_session: Session) -> None:
    """``delete_knowledge_edge`` removes the row and records a delete audit event."""
    parent_id, child_id = _seed_pair(db_session)
    edge = create_knowledge_edge(
        db_session,
        source_node_id=parent_id,
        target_node_id=child_id,
        edge_type="prerequisite",
        scope="personal",
        actor_id="u:a",
    )
    db_session.commit()
    edge_id = edge.id

    delete_knowledge_edge(db_session, edge, actor_id="u:a")
    db_session.commit()

    assert get_knowledge_edge(db_session, edge_id, scope="personal") is None
    audit = db_session.query(AuditLog).filter_by(entity_id=edge_id, action="delete").one()
    assert audit.entity_type == "KnowledgeEdge"
