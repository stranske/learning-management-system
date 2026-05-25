"""Tests for learner learning goals."""

from __future__ import annotations

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
