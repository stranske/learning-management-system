"""Knowledge graph model constraint tests."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from lms.graphs.repository import (
    create_graph_reference,
    create_knowledge_edge,
    create_knowledge_node,
)


def test_normal_edge_cannot_cross_ownership_scope(db_session: Session) -> None:
    """Normal prerequisite edges cannot cross personal/institutional scopes."""
    personal = create_knowledge_node(
        db_session,
        title="Spaced repetition",
        knowledge_type="concept",
        ownership_scope="personal",
        actor_id="user:alice",
    )
    institutional = create_knowledge_node(
        db_session,
        title="Course retention target",
        knowledge_type="principle",
        ownership_scope="institutional",
        actor_id="user:alice",
    )

    with pytest.raises(IntegrityError):
        create_knowledge_edge(
            db_session,
            source_node_id=personal.id,
            target_node_id=institutional.id,
            edge_type="prerequisite",
            actor_id="user:alice",
        )
        db_session.commit()


def test_cross_scope_edge_requires_explicit_graph_reference(db_session: Session) -> None:
    """Cross-scope references require a separate authorization row."""
    personal = create_knowledge_node(
        db_session,
        title="Learner note",
        knowledge_type="fact",
        ownership_scope="personal",
        actor_id="user:alice",
    )
    institutional = create_knowledge_node(
        db_session,
        title="Curriculum concept",
        knowledge_type="concept",
        ownership_scope="institutional",
        actor_id="user:alice",
    )
    reference = create_graph_reference(
        db_session,
        source_scope="personal",
        target_scope="institutional",
        reason="Learner note cites the shared course concept.",
        actor_id="user:alice",
    )

    edge = create_knowledge_edge(
        db_session,
        source_node_id=personal.id,
        target_node_id=institutional.id,
        edge_type="cross-scope-reference",
        graph_reference_id=reference.id,
        actor_id="user:alice",
    )
    db_session.commit()

    assert edge.source_scope == "personal"
    assert edge.target_scope == "institutional"
    assert edge.graph_reference_id == reference.id
