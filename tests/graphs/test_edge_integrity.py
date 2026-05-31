"""Edge-integrity tests: prerequisite cycles and duplicate edges are rejected.

Source: 2026-05-30 multi-agent audit (issue #198). The edge-creation path
previously guarded only direct self-loops, so a multi-hop prerequisite cycle
(``A -> B -> C -> A``) and exact duplicate edges both committed silently,
leaving a prerequisite graph with no valid topological learning order.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from lms.graphs.repository import create_knowledge_edge, create_knowledge_node


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
