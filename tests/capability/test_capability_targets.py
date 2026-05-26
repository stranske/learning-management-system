"""Tests for personal capability target repository helpers."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from lms.auth.models import User
from lms.capability.repository import (
    archive_capability_target,
    create_capability_target,
    list_capability_targets,
    update_capability_target,
)
from lms.competencies.repository import create_competency
from lms.graphs.repository import create_knowledge_node
from lms.learners.repository import create_learner_for_user, create_learning_goal


def _learner(db_session: Session) -> str:
    user = User(
        email="learner@example.test",
        username="learner",
        display_name="Learner",
    )
    db_session.add(user)
    db_session.flush()
    return create_learner_for_user(
        db_session,
        user_id=user.id,
        display_name="Learner",
    ).id


def test_capability_target_requires_personal_scope(db_session: Session) -> None:
    """Capability targets are explicitly personal-scope in M5."""
    learner_id = _learner(db_session)
    node = create_knowledge_node(
        db_session,
        title="Institutional policy node",
        knowledge_type="conceptual",
        scope="institutional",
        actor_id="user:alice",
        status="published",
    )

    with pytest.raises(ValueError, match="ownership_scope='personal'"):
        create_capability_target(
            db_session,
            learner_id=learner_id,
            title="Institutional capability",
            ownership_scope="institutional",
            target_node_ids=[node.id],
        )


def test_capability_target_links_nodes_and_competencies(db_session: Session) -> None:
    """A target can combine personal graph nodes, competencies, and evidence expectations."""
    learner_id = _learner(db_session)
    node = create_knowledge_node(
        db_session,
        title="Explain evidence tradeoffs",
        knowledge_type="judgment",
        scope="personal",
        actor_id="user:alice",
        status="published",
    )
    goal = create_learning_goal(
        db_session,
        learner_id=learner_id,
        title="Evidence reasoning",
        knowledge_type="judgment",
        target_node_ids=[node.id],
        ownership_scope="personal",
    )
    competency = create_competency(
        db_session,
        title="Evidence-backed judgment",
        ownership_scope="personal",
        target_knowledge_type="judgment",
        status="active",
    )

    target = create_capability_target(
        db_session,
        learner_id=learner_id,
        title="Reach durable evidence-backed judgment",
        learning_goal_id=goal.id,
        target_node_ids=[node.id],
        target_competency_ids=[competency.id],
        required_evidence_types=["rubric-score", "transfer-case"],
        confidence_threshold=0.85,
    )
    db_session.commit()

    assert target.ownership_scope == "personal"
    assert target.learning_goal_id == goal.id
    assert [linked.id for linked in target.target_nodes] == [node.id]
    assert [linked.id for linked in target.target_competencies] == [competency.id]
    assert target.required_evidence_types == ["rubric-score", "transfer-case"]
    assert list_capability_targets(db_session, learner_id=learner_id) == [target]


def test_capability_target_validates_goal_and_link_scopes(db_session: Session) -> None:
    """Targets cannot drift outside their personal learning goal or competency scope."""
    learner_id = _learner(db_session)
    goal_node = create_knowledge_node(
        db_session,
        title="Goal node",
        knowledge_type="conceptual",
        scope="personal",
        actor_id="user:alice",
        status="published",
    )
    other_node = create_knowledge_node(
        db_session,
        title="Other node",
        knowledge_type="conceptual",
        scope="personal",
        actor_id="user:alice",
        status="published",
    )
    goal = create_learning_goal(
        db_session,
        learner_id=learner_id,
        title="Constrained goal",
        knowledge_type="conceptual",
        target_node_ids=[goal_node.id],
        ownership_scope="personal",
    )
    institutional_competency = create_competency(
        db_session,
        title="Institutional competency",
        ownership_scope="institutional",
        target_knowledge_type="conceptual",
    )

    with pytest.raises(ValueError, match="linked to the learning goal"):
        create_capability_target(
            db_session,
            learner_id=learner_id,
            title="Outside goal target",
            learning_goal_id=goal.id,
            target_node_ids=[other_node.id],
        )

    with pytest.raises(ValueError, match="target competencies not found"):
        create_capability_target(
            db_session,
            learner_id=learner_id,
            title="Cross-scope competency target",
            target_node_ids=[goal_node.id],
            target_competency_ids=[institutional_competency.id],
        )


def test_update_and_archive_capability_target(db_session: Session) -> None:
    """Targets can be updated and archived without deleting planning history."""
    learner_id = _learner(db_session)
    node = create_knowledge_node(
        db_session,
        title="Original node",
        knowledge_type="procedural",
        scope="personal",
        actor_id="user:alice",
        status="published",
    )
    target = create_capability_target(
        db_session,
        learner_id=learner_id,
        title="Original target",
        target_node_ids=[node.id],
    )

    updated = update_capability_target(
        db_session,
        target,
        title="Updated target",
        required_evidence_types=["attempt", "self-explanation"],
        confidence_threshold=0.9,
    )
    archived = archive_capability_target(db_session, updated)
    db_session.commit()

    assert archived.title == "Updated target"
    assert archived.required_evidence_types == ["attempt", "self-explanation"]
    assert archived.confidence_threshold == 0.9
    assert archived.status == "archived"
