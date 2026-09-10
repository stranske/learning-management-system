"""Edge-integrity tests: prerequisite cycles and duplicate edges are rejected.

Source: 2026-05-30 multi-agent audit (issue #198). The edge-creation path
previously guarded only direct self-loops, so a multi-hop prerequisite cycle
(``A -> B -> C -> A``) and exact duplicate edges both committed silently,
leaving a prerequisite graph with no valid topological learning order.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from lms.audit.models import AuditLog
from lms.graphs.repository import (
    CLEARABLE_EDGE_FIELDS,
    ORDERING_EDGE_TYPES,
    _ordering_edge_closes_cycle,
    create_knowledge_edge,
    create_knowledge_node,
    update_knowledge_edge,
)


def _seed_nodes(session: Session, count: int, *, scope: str = "personal") -> list[str]:
    ids: list[str] = []
    for index in range(count):
        node = create_knowledge_node(
            session,
            title=f"Node {index}",
            knowledge_type="conceptual",
            scope=scope,
            actor_id="user:alice",
        )
        ids.append(node.id)
    session.commit()
    return ids


def test_prerequisite_cycle_rejected(db_session: Session) -> None:
    """``A -> B -> C`` commits but the closing ``C -> A`` raises."""
    a, b, c = _seed_nodes(db_session, 3)

    create_knowledge_edge(
        db_session,
        source_node_id=a,
        target_node_id=b,
        edge_type="prerequisite",
        scope="personal",
        actor_id="user:alice",
    )
    create_knowledge_edge(
        db_session,
        source_node_id=b,
        target_node_id=c,
        edge_type="prerequisite",
        scope="personal",
        actor_id="user:alice",
    )
    db_session.commit()

    with pytest.raises(ValueError, match="prerequisite cycle"):
        create_knowledge_edge(
            db_session,
            source_node_id=c,
            target_node_id=a,
            edge_type="prerequisite",
            scope="personal",
            actor_id="user:alice",
        )


def test_cycle_guard_spans_ordering_class(db_session: Session) -> None:
    """A cycle that mixes ordering edge types is still rejected.

    ``prerequisite`` and ``key-prerequisite`` both impose a learning order, so
    ``A -prerequisite-> B`` plus a closing ``B -key-prerequisite-> A`` is a
    contradictory ordering and must raise.
    """
    a, b = _seed_nodes(db_session, 2)

    create_knowledge_edge(
        db_session,
        source_node_id=a,
        target_node_id=b,
        edge_type="prerequisite",
        scope="personal",
        actor_id="user:alice",
    )
    db_session.commit()

    with pytest.raises(ValueError, match="prerequisite cycle"):
        create_knowledge_edge(
            db_session,
            source_node_id=b,
            target_node_id=a,
            edge_type="key-prerequisite",
            scope="personal",
            actor_id="user:alice",
        )


def test_non_ordering_edge_allows_back_reference(db_session: Session) -> None:
    """Non-ordering edge types (e.g. ``analogy``) are not cycle-guarded."""
    a, b = _seed_nodes(db_session, 2)

    create_knowledge_edge(
        db_session,
        source_node_id=a,
        target_node_id=b,
        edge_type="analogy",
        scope="personal",
        actor_id="user:alice",
    )
    # The reverse analogy is a legitimate symmetric relation, not a cycle.
    edge = create_knowledge_edge(
        db_session,
        source_node_id=b,
        target_node_id=a,
        edge_type="analogy",
        scope="personal",
        actor_id="user:alice",
    )
    db_session.commit()
    assert edge.id is not None


def test_duplicate_edge_rejected(db_session: Session) -> None:
    """An exact duplicate (source, target, edge_type, scope) raises."""
    a, b = _seed_nodes(db_session, 2)

    create_knowledge_edge(
        db_session,
        source_node_id=a,
        target_node_id=b,
        edge_type="prerequisite",
        scope="personal",
        actor_id="user:alice",
    )
    db_session.commit()

    with pytest.raises(ValueError, match="duplicate knowledge edge"):
        create_knowledge_edge(
            db_session,
            source_node_id=a,
            target_node_id=b,
            edge_type="prerequisite",
            scope="personal",
            actor_id="user:alice",
        )


@pytest.mark.parametrize("scope", ["personal", "institutional"])
@pytest.mark.parametrize("path_length", [2, 3])
@pytest.mark.parametrize(
    ("old_type", "new_type"),
    [
        ("analogy", "prerequisite"),
        ("contrast", "key-prerequisite"),
        ("transfer-context", "encompassing"),
    ],
)
def test_update_rejects_ordering_cycle_without_mutation(
    db_session: Session, scope: str, path_length: int, old_type: str, new_type: str
) -> None:
    """Rejected type changes preserve pending work and leave the session usable."""
    nodes = _seed_nodes(db_session, path_length, scope=scope)
    for index, (source, target) in enumerate(zip(nodes, nodes[1:], strict=False)):
        create_knowledge_edge(
            db_session,
            source_node_id=source,
            target_node_id=target,
            edge_type=ORDERING_EDGE_TYPES[index],
            scope=scope,
            actor_id="user:alice",
        )
    edge = create_knowledge_edge(
        db_session,
        source_node_id=nodes[-1],
        target_node_id=nodes[0],
        edge_type=old_type,
        scope=scope,
        actor_id="user:alice",
        notes="original",
    )
    audit_count = db_session.query(AuditLog).count()
    with pytest.raises(ValueError, match="edge would create a prerequisite cycle"):
        update_knowledge_edge(
            db_session,
            edge,
            actor_id="user:alice",
            notes="must not persist",
            edge_type=new_type,
        )
    assert (edge.edge_type, edge.notes) == (old_type, "original")
    assert db_session.is_active
    assert not db_session.dirty
    assert db_session.query(AuditLog).count() == audit_count
    # No rollback: prior uncommitted edges and audit events must survive.
    update_knowledge_edge(db_session, edge, actor_id="user:alice", status="published")
    db_session.commit()
    db_session.refresh(edge)
    assert (edge.edge_type, edge.notes, edge.status) == (old_type, "original", "published")
    assert db_session.query(AuditLog).count() == audit_count + 1


@pytest.mark.parametrize("edge_type", ORDERING_EDGE_TYPES)
def test_update_allows_acyclic_ordering_changes(db_session: Session, edge_type: str) -> None:
    """Converting an edge and reapplying its ordering type both remain valid."""
    a, b = _seed_nodes(db_session, 2)
    edge = create_knowledge_edge(
        db_session,
        source_node_id=a,
        target_node_id=b,
        edge_type="analogy",
        scope="personal",
        actor_id="user:alice",
    )
    update_knowledge_edge(db_session, edge, actor_id="user:alice", edge_type=edge_type)
    update_knowledge_edge(
        db_session,
        edge,
        actor_id="user:alice",
        edge_type=edge_type,
        notes="updated",
    )
    db_session.commit()
    db_session.refresh(edge)
    assert (edge.edge_type, edge.notes) == (edge_type, "updated")
    audits = db_session.query(AuditLog).filter_by(entity_id=edge.id, action="update").all()
    assert len(audits) == 2
    assert audits[0].before_summary is not None and audits[0].after_summary is not None
    assert audits[0].before_summary["edge_type"] == "analogy"
    assert audits[0].after_summary["edge_type"] == edge_type


def test_update_rejects_duplicate_edge_type_a_cycle_check_cannot_see(
    db_session: Session,
) -> None:
    """Retyping a parallel edge onto a sibling's type is refused as a duplicate.

    Two edges may share endpoints while differing in type. Retyping one onto the
    other's type reaches a state ``create_knowledge_edge`` refuses, and the cycle
    check cannot substitute for the duplicate check here: both edges run
    ``source -> target``, so no cycle is closed and reachability reports False.
    """
    a, b = _seed_nodes(db_session, 2)
    kept = create_knowledge_edge(
        db_session,
        source_node_id=a,
        target_node_id=b,
        edge_type="prerequisite",
        scope="personal",
        actor_id="user:alice",
    )
    parallel = create_knowledge_edge(
        db_session,
        source_node_id=a,
        target_node_id=b,
        edge_type="analogy",
        scope="personal",
        actor_id="user:alice",
        notes="original",
    )
    audit_count = db_session.query(AuditLog).count()

    # The cycle check on its own does not object: the sibling points the same way.
    assert not _ordering_edge_closes_cycle(
        db_session,
        source_node_id=parallel.source_node_id,
        target_node_id=parallel.target_node_id,
        scope=parallel.source_scope,
        exclude_edge_id=parallel.id,
    )
    with pytest.raises(ValueError, match="duplicate knowledge edge"):
        update_knowledge_edge(
            db_session,
            parallel,
            actor_id="user:alice",
            edge_type="prerequisite",
            notes="must not persist",
        )
    assert (parallel.edge_type, parallel.notes) == ("analogy", "original")
    assert kept.edge_type == "prerequisite"
    assert db_session.is_active
    assert not db_session.dirty
    assert db_session.query(AuditLog).count() == audit_count

    # A type no sibling holds still applies normally.
    update_knowledge_edge(db_session, parallel, actor_id="user:alice", edge_type="contrast")
    db_session.commit()
    db_session.refresh(parallel)
    assert parallel.edge_type == "contrast"
    assert db_session.query(AuditLog).count() == audit_count + 1


def test_update_reapplying_an_unchanged_edge_type_is_not_a_duplicate(
    db_session: Session,
) -> None:
    """The duplicate check keys off a *change* of type, never off the edge itself."""
    a, b = _seed_nodes(db_session, 2)
    edge = create_knowledge_edge(
        db_session,
        source_node_id=a,
        target_node_id=b,
        edge_type="prerequisite",
        scope="personal",
        actor_id="user:alice",
    )
    update_knowledge_edge(
        db_session,
        edge,
        actor_id="user:alice",
        edge_type="prerequisite",
        notes="unchanged type",
    )
    db_session.commit()
    db_session.refresh(edge)
    assert (edge.edge_type, edge.notes) == ("prerequisite", "unchanged type")


@pytest.mark.parametrize("field", sorted(CLEARABLE_EDGE_FIELDS))
def test_update_clears_nullable_fields_on_explicit_none(db_session: Session, field: str) -> None:
    """An explicit ``None`` clears a nullable column instead of being skipped."""
    a, b = _seed_nodes(db_session, 2)
    edge = create_knowledge_edge(
        db_session,
        source_node_id=a,
        target_node_id=b,
        edge_type="analogy",
        scope="personal",
        actor_id="user:alice",
        confidence=0.5,
        notes="original",
    )
    db_session.commit()
    assert getattr(edge, field) is not None

    update_knowledge_edge(db_session, edge, actor_id="user:alice", **{field: None})
    db_session.commit()
    db_session.refresh(edge)
    assert getattr(edge, field) is None
    # The field NOT cleared this round is untouched, so clearing is per-field.
    other = next(iter(CLEARABLE_EDGE_FIELDS - {field}))
    assert getattr(edge, other) is not None


@pytest.mark.parametrize("field", ["edge_type", "status"])
def test_update_rejects_clearing_a_required_field(db_session: Session, field: str) -> None:
    """``edge_type`` and ``status`` are ``nullable=False``; clearing them is an error."""
    a, b = _seed_nodes(db_session, 2)
    edge = create_knowledge_edge(
        db_session,
        source_node_id=a,
        target_node_id=b,
        edge_type="analogy",
        scope="personal",
        actor_id="user:alice",
    )
    db_session.commit()
    audit_count = db_session.query(AuditLog).count()
    before = (edge.edge_type, edge.status)

    with pytest.raises(ValueError, match=f"{field} cannot be cleared"):
        update_knowledge_edge(db_session, edge, actor_id="user:alice", **{field: None})
    assert (edge.edge_type, edge.status) == before
    assert db_session.is_active
    assert not db_session.dirty
    assert db_session.query(AuditLog).count() == audit_count
