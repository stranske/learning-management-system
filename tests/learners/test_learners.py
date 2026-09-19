"""Tests for learner profile persistence."""

from __future__ import annotations

import math
from unittest.mock import Mock

import pytest
from sqlalchemy.orm import Session

from lms.auth.repository import create_local_user
from lms.evidence.repository import create_evidence_record
from lms.graphs.repository import create_knowledge_node
from lms.learners.repository import (
    create_learner_for_user,
    create_learning_goal,
    goal_progress_for_learner,
    list_learners_for_user,
)


def test_create_learner_for_user(db_session: Session) -> None:
    """A learner profile is explicitly linked to a user id."""
    user = create_local_user(db_session, username="grace", display_name="Grace Hopper")
    learner = create_learner_for_user(
        db_session,
        user_id=user.id,
        display_name="Grace",
        timezone="America/Chicago",
    )
    db_session.commit()

    assert learner.id
    assert learner.user_id == user.id
    assert learner.display_name == "Grace"
    assert learner.timezone == "America/Chicago"
    assert learner.locale == "en-US"
    assert list_learners_for_user(db_session, user_id=user.id) == [learner]


@pytest.fixture
def goal_with_mastery(db_session: Session) -> tuple[str, str]:
    """Persist a goal whose three nodes have mastery estimates 0, 0.5 and 1."""
    user = create_local_user(db_session, username="ada", display_name="Ada")
    learner = create_learner_for_user(db_session, user_id=user.id, display_name="Ada")
    node_ids = []
    for score in (0.0, 0.5, 1.0):
        node = create_knowledge_node(
            db_session,
            title=f"Concept {score}",
            knowledge_type="conceptual",
            scope="personal",
            actor_id=user.id,
            status="published",
        )
        node_ids.append(node.id)
        create_evidence_record(
            db_session,
            learner_id=learner.id,
            knowledge_node_id=node.id,
            knowledge_type="conceptual",
            normalized_score=score,
        )
    goal = create_learning_goal(
        db_session,
        learner_id=learner.id,
        title="Master the concepts",
        knowledge_type="conceptual",
        target_node_ids=node_ids,
        ownership_scope="personal",
    )
    db_session.commit()
    return learner.id, goal.id


@pytest.mark.parametrize(
    "threshold",
    [
        float("nan"),
        float("inf"),
        float("-inf"),
        -0.1,
        1.1,
        1.5,
        math.nextafter(0.0, -math.inf),
        math.nextafter(1.0, math.inf),
    ],
)
@pytest.mark.parametrize("goal_state", ["populated", "fully_mastered", "no_evidence", "missing"])
def test_goal_progress_rejects_invalid_mastery_threshold(
    db_session: Session,
    goal_with_mastery: tuple[str, str],
    threshold: float,
    goal_state: str,
) -> None:
    """Invalid thresholds fail regardless of goal existence or mastery evidence."""
    learner_id, goal_id = goal_with_mastery
    requested_goal_id = goal_id
    if goal_state in {"fully_mastered", "no_evidence"}:
        node = create_knowledge_node(
            db_session,
            title="Mastered concept",
            knowledge_type="conceptual",
            scope="personal",
            actor_id="test-actor",
            status="published",
        )
        if goal_state == "fully_mastered":
            create_evidence_record(
                db_session,
                learner_id=learner_id,
                knowledge_node_id=node.id,
                knowledge_type="conceptual",
                normalized_score=1.0,
            )
        separate_goal = create_learning_goal(
            db_session,
            learner_id=learner_id,
            title=f"Goal with {goal_state}",
            knowledge_type="conceptual",
            target_node_ids=[node.id],
            ownership_scope="personal",
        )
        db_session.commit()
        requested_goal_id = separate_goal.id
    elif goal_state == "missing":
        requested_goal_id = "missing-goal"

    with pytest.raises(ValueError) as error:
        goal_progress_for_learner(
            db_session,
            learner_id=learner_id,
            goal_id=requested_goal_id,
            mastery_threshold=threshold,
        )
    assert str(error.value) == (
        "mastery_threshold must be a finite float between 0.0 and 1.0 (inclusive)"
    )

    # Rejection leaves the session usable and the persisted evidence intact.
    db_session.commit()
    progress = goal_progress_for_learner(db_session, learner_id=learner_id, goal_id=goal_id)
    assert progress["covered_count"] == 3
    assert progress["mastered_count"] == 1
    assert progress["progress"] == pytest.approx(1 / 3, abs=1e-4)


@pytest.mark.parametrize("threshold", [float("nan"), float("inf"), float("-inf"), -0.1, 1.1])
def test_goal_progress_rejects_invalid_threshold_before_session_access(threshold: float) -> None:
    """Invalid input must fail before any database query or session mutation."""
    session = Mock(spec=Session)

    with pytest.raises(ValueError) as error:
        goal_progress_for_learner(
            session,
            learner_id="unused-learner",
            goal_id="unused-goal",
            mastery_threshold=threshold,
        )

    assert str(error.value) == (
        "mastery_threshold must be a finite float between 0.0 and 1.0 (inclusive)"
    )
    assert session.mock_calls == []


@pytest.mark.parametrize(
    "threshold, mastered",
    [
        (0.0, 3),
        (math.nextafter(0.0, math.inf), 2),
        (math.nextafter(0.5, -math.inf), 2),
        (0.5, 2),
        (math.nextafter(0.5, math.inf), 1),
        (0.8, 1),
        (math.nextafter(1.0, -math.inf), 1),
        (1.0, 1),
    ],
)
def test_goal_progress_accepts_unit_interval_thresholds(
    db_session: Session,
    goal_with_mastery: tuple[str, str],
    threshold: float,
    mastered: int,
) -> None:
    """Endpoints and interior thresholds retain inclusive mastery comparisons."""
    learner_id, goal_id = goal_with_mastery
    progress = goal_progress_for_learner(
        db_session, learner_id=learner_id, goal_id=goal_id, mastery_threshold=threshold
    )
    assert progress["target_count"] == 3
    assert progress["covered_count"] == 3
    assert progress["mastered_count"] == mastered
    assert progress["mastery_threshold"] == threshold
    assert progress["progress"] == pytest.approx(mastered / 3, abs=1e-4)
