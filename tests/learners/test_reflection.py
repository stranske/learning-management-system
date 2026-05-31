"""Tests for reflection prompts and goal-relative progress (issue #204)."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from lms.auth.repository import create_local_user
from lms.evidence.repository import create_evidence_record
from lms.graphs.repository import create_knowledge_node
from lms.learners.repository import (
    create_learner_for_user,
    create_learning_goal,
    create_reflection,
    goal_progress_for_learner,
    list_reflections_for_learner,
)


def test_reflection_prompt_persisted_and_surfaced(db_session: Session) -> None:
    """A submitted reflection is stored and returned by the learner surface."""
    user = create_local_user(db_session, username="ada", display_name="Ada Lovelace")
    learner = create_learner_for_user(db_session, user_id=user.id, display_name="Ada")
    node = create_knowledge_node(
        db_session,
        title="Spaced retrieval",
        knowledge_type="procedural",
        scope="personal",
        actor_id=user.id,
        status="published",
    )

    create_reflection(
        db_session,
        learner_id=learner.id,
        prompt="What did you find hardest in this review, and why?",
        response="I keep confusing the two retrieval cues; I will slow down next time.",
        knowledge_node_id=node.id,
    )
    db_session.commit()

    surfaced = list_reflections_for_learner(db_session, learner_id=learner.id)

    assert len(surfaced) == 1
    assert surfaced[0].prompt == "What did you find hardest in this review, and why?"
    assert surfaced[0].response.startswith("I keep confusing")
    assert surfaced[0].knowledge_node_id == node.id


def test_reflection_requires_non_empty_response(db_session: Session) -> None:
    """A reflection with no response text is rejected, not silently dropped."""
    user = create_local_user(db_session, username="grace", display_name="Grace Hopper")
    learner = create_learner_for_user(db_session, user_id=user.id, display_name="Grace")

    with pytest.raises(ValueError, match="response"):
        create_reflection(
            db_session,
            learner_id=learner.id,
            prompt="What will you try next time?",
            response="   ",
        )


def test_goal_progress_equals_mastered_over_target_ratio(db_session: Session) -> None:
    """Goal progress equals the mastered/target ratio for a known fixture."""
    user = create_local_user(db_session, username="maria", display_name="Maria Mitchell")
    learner = create_learner_for_user(db_session, user_id=user.id, display_name="Maria")

    mastered_high = create_knowledge_node(
        db_session,
        title="Concept A",
        knowledge_type="conceptual",
        scope="personal",
        actor_id=user.id,
        status="published",
    )
    mastered_mid = create_knowledge_node(
        db_session,
        title="Concept B",
        knowledge_type="conceptual",
        scope="personal",
        actor_id=user.id,
        status="published",
    )
    unmastered = create_knowledge_node(
        db_session,
        title="Concept C",
        knowledge_type="conceptual",
        scope="personal",
        actor_id=user.id,
        status="published",
    )

    goal = create_learning_goal(
        db_session,
        learner_id=learner.id,
        title="Master the core concepts",
        knowledge_type="conceptual",
        target_node_ids=[mastered_high.id, mastered_mid.id, unmastered.id],
        ownership_scope="personal",
    )

    # Two nodes reach the 0.8 mastery threshold; one stays below it.
    create_evidence_record(
        db_session,
        learner_id=learner.id,
        knowledge_node_id=mastered_high.id,
        knowledge_type="conceptual",
        normalized_score=1.0,
    )
    create_evidence_record(
        db_session,
        learner_id=learner.id,
        knowledge_node_id=mastered_mid.id,
        knowledge_type="conceptual",
        normalized_score=0.9,
    )
    create_evidence_record(
        db_session,
        learner_id=learner.id,
        knowledge_node_id=unmastered.id,
        knowledge_type="conceptual",
        normalized_score=0.3,
    )
    db_session.commit()

    progress = goal_progress_for_learner(db_session, learner_id=learner.id, goal_id=goal.id)

    assert progress["target_count"] == 3
    assert progress["covered_count"] == 3
    assert progress["mastered_count"] == 2
    assert progress["progress"] == pytest.approx(2 / 3, abs=1e-4)
