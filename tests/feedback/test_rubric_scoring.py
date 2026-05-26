"""Tests for rubric scoring and partial-credit evidence."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from lms.evidence.repository import create_attempt, get_evidence_record
from lms.feedback.repository import create_rubric, get_feedback_record, list_feedback_actions
from lms.feedback.scoring import InvalidRubricScoringError, score_attempt_with_rubric
from lms.graphs.repository import create_knowledge_node


def _attempt(db_session: Session) -> str:
    attempt = create_attempt(
        db_session,
        learner_id="learner-1",
        prompt_id="prompt-1",
        response_text="I isolated the variable but skipped evidence.",
        feedback={
            "goal": "Explain algebra steps",
            "observed_evidence": "Attempt submitted.",
            "next_action": "Review the worked example.",
        },
    )
    return attempt.id


def _rubric(db_session: Session) -> tuple[str, list[str]]:
    node = create_knowledge_node(
        db_session,
        title="Linear equations",
        knowledge_type="procedural",
        scope="personal",
        actor_id="user:alice",
        status="published",
    )
    rubric = create_rubric(
        db_session,
        title="Equation reasoning",
        ownership_scope="personal",
        authoring_actor="user:alice",
        knowledge_node_id=node.id,
        criteria=[
            {
                "criterion_order": 1,
                "description": "States the transformation.",
                "max_points": 2,
            },
            {
                "criterion_order": 2,
                "description": "Justifies each step.",
                "max_points": 3,
            },
        ],
    )
    return rubric.id, [criterion.id for criterion in rubric.criteria]


def test_rubric_score_writes_partial_credit_evidence(db_session: Session) -> None:
    """Rubric scoring stores raw, normalized, max, and criterion-level evidence."""
    attempt_id = _attempt(db_session)
    rubric_id, criterion_ids = _rubric(db_session)

    score = score_attempt_with_rubric(
        db_session,
        rubric_id=rubric_id,
        attempt_id=attempt_id,
        scorer_type="human",
        scorer_id="teacher-1",
        scorer_version="rubric-v1",
        criterion_scores=[
            {"criterion_id": criterion_ids[0], "points": 2, "rationale": "Clear step."},
            {"criterion_id": criterion_ids[1], "points": 2, "rationale": "Needs more detail."},
        ],
    )
    db_session.commit()

    assert score.evidence_record_id is not None
    evidence = get_evidence_record(db_session, score.evidence_record_id)
    assert evidence is not None
    assert score.raw_score == 4
    assert score.max_score == 5
    assert score.normalized_score == 0.8
    assert evidence.raw_score == 4
    assert evidence.max_score == 5
    assert evidence.normalized_score == 0.8
    assert evidence.scorer_metadata is not None
    assert evidence.partial_credit_dimensions is not None
    assert evidence.scorer_metadata["scoring_method"] == "rubric"
    assert evidence.partial_credit_dimensions["rubric_id"] == rubric_id
    assert evidence.partial_credit_dimensions["criterion_scores"][1]["points"] == 2


def test_low_rubric_score_creates_revision_or_remediation_feedback_action(
    db_session: Session,
) -> None:
    """Low rubric scores create durable feedback and next actions."""
    attempt_id = _attempt(db_session)
    rubric_id, criterion_ids = _rubric(db_session)

    score = score_attempt_with_rubric(
        db_session,
        rubric_id=rubric_id,
        attempt_id=attempt_id,
        scorer_type="human",
        criterion_scores=[
            {"criterion_id": criterion_ids[0], "points": 1},
            {"criterion_id": criterion_ids[1], "points": 1},
        ],
    )
    db_session.commit()

    assert score.feedback_record_id is not None
    feedback = get_feedback_record(db_session, score.feedback_record_id)
    assert feedback is not None
    assert feedback.feedback_level == "remediation"
    assert feedback.evidence_record_id == score.evidence_record_id
    actions = list_feedback_actions(
        db_session,
        learner_id="learner-1",
        feedback_record_id=feedback.id,
    )
    assert len(actions) == 1
    assert actions[0].action_type == "prerequisite-remediation"
    assert feedback.next_action_ids == [actions[0].id]


def test_rubric_score_requires_every_active_criterion(db_session: Session) -> None:
    """Omitting an active criterion must raise rather than inflate the normalized score."""
    attempt_id = _attempt(db_session)
    rubric_id, criterion_ids = _rubric(db_session)

    with pytest.raises(InvalidRubricScoringError, match="every active rubric criterion"):
        score_attempt_with_rubric(
            db_session,
            rubric_id=rubric_id,
            attempt_id=attempt_id,
            scorer_type="human",
            criterion_scores=[
                {"criterion_id": criterion_ids[0], "points": 2},
            ],
        )
