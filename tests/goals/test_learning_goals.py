"""Tests for learner learning goals."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from lms.auth.repository import create_local_user
from lms.graphs.repository import create_knowledge_node
from lms.learners.repository import (
    create_learner_for_user,
    create_learning_goal,
    list_learning_goals_for_learner,
)


def test_create_knowledge_type_tagged_goal(db_session: Session) -> None:
    """A learner can create a knowledge-type-tagged goal for published nodes."""
    user = create_local_user(db_session, username="ada", display_name="Ada Lovelace")
    learner = create_learner_for_user(
        db_session,
        user_id=user.id,
        display_name="Ada",
    )
    node = create_knowledge_node(
        db_session,
        title="Retrieval practice",
        knowledge_type="conceptual",
        scope="personal",
        actor_id=user.id,
        status="published",
    )

    goal = create_learning_goal(
        db_session,
        learner_id=learner.id,
        title="Understand retrieval practice",
        knowledge_type="conceptual",
        target_node_ids=[node.id],
        ownership_scope="personal",
    )
    db_session.commit()

    assert goal.id
    assert goal.status == "active"
    assert goal.learner_id == learner.id
    assert goal.knowledge_type == "conceptual"
    assert goal.ownership_scope == "personal"
    assert [target.id for target in goal.target_nodes] == [node.id]
    assert list_learning_goals_for_learner(db_session, learner_id=learner.id) == [goal]


def test_create_learning_goal_rejects_draft_target_node(db_session: Session) -> None:
    """Learning goals cannot target draft knowledge nodes."""
    user = create_local_user(db_session, username="grace", display_name="Grace Hopper")
    learner = create_learner_for_user(
        db_session,
        user_id=user.id,
        display_name="Grace",
    )
    draft_node = create_knowledge_node(
        db_session,
        title="Unpublished draft",
        knowledge_type="conceptual",
        scope="personal",
        actor_id=user.id,
        status="draft",
    )

    with pytest.raises(ValueError, match="published knowledge nodes"):
        create_learning_goal(
            db_session,
            learner_id=learner.id,
            title="Should fail for draft target",
            knowledge_type="conceptual",
            target_node_ids=[draft_node.id],
            ownership_scope="personal",
        )


def test_create_learning_goal_rejects_cross_scope_target_node(db_session: Session) -> None:
    """Learning goals must target nodes in the same ownership scope."""
    user = create_local_user(db_session, username="edsger", display_name="Edsger Dijkstra")
    learner = create_learner_for_user(
        db_session,
        user_id=user.id,
        display_name="Edsger",
    )
    institutional_node = create_knowledge_node(
        db_session,
        title="Institutional-only concept",
        knowledge_type="conceptual",
        scope="institutional",
        actor_id=user.id,
        status="published",
    )

    with pytest.raises(ValueError, match="not found in this scope"):
        create_learning_goal(
            db_session,
            learner_id=learner.id,
            title="Should fail for cross-scope target",
            knowledge_type="conceptual",
            target_node_ids=[institutional_node.id],
            ownership_scope="personal",
        )
