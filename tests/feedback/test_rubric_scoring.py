"""Tests for rubric scoring and partial-credit evidence."""

from __future__ import annotations

import math
from unittest.mock import Mock

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from lms.evidence.models import EvidenceRecord
from lms.evidence.repository import create_attempt, get_evidence_record
from lms.feedback.models import FeedbackAction, FeedbackRecord, RubricScore
from lms.feedback.repository import create_rubric, get_feedback_record, list_feedback_actions
from lms.feedback.scoring import (
    AttemptNotFoundError,
    InvalidRubricScoringError,
    RubricNotFoundError,
    score_attempt_with_rubric,
)
from lms.graphs.repository import create_knowledge_node
from lms.scheduling.models import ReviewCardState, ReviewQueueItem


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
    assert evidence.partial_credit_dimensions is not None
    assert evidence.scoring_method == "rubric-scored"
    assert evidence.scorer_type == "human"
    assert evidence.scorer_id == "teacher-1"
    assert evidence.scorer_version == "rubric-v1"
    assert evidence.partial_credit_dimensions["rubric_id"] == rubric_id
    assert evidence.partial_credit_dimensions["criterion_scores"][1]["points"] == 2


@pytest.mark.parametrize(
    ("feedback_threshold", "remediation_threshold", "message"),
    [
        (value, 0.5, "feedback_threshold must be a finite number between 0.0 and 1.0")
        for value in [
            float("nan"),
            float("inf"),
            float("-inf"),
            -0.1,
            1.1,
            math.nextafter(0.0, -math.inf),
            math.nextafter(1.0, math.inf),
        ]
    ]
    + [
        (0.85, value, "remediation_threshold must be a finite number between 0.0 and 1.0")
        for value in [
            float("nan"),
            float("inf"),
            float("-inf"),
            -0.1,
            1.1,
            math.nextafter(0.0, -math.inf),
            math.nextafter(1.0, math.inf),
        ]
    ]
    + [
        (feedback, remediation, "remediation_threshold cannot exceed feedback_threshold")
        for feedback, remediation in [
            (0.4, 0.8),
            (0.0, 0.5),
            (0.85, 1.0),
            # Even adjacent floats must respect threshold ordering.
            (0.0, math.nextafter(0.0, math.inf)),
            (0.5, math.nextafter(0.5, math.inf)),
            (math.nextafter(1.0, 0.0), 1.0),
        ]
    ],
)
@pytest.mark.parametrize(
    "points",
    [(0, 0), (1, 1), (2, 3)],
    ids=["zero-credit", "partial-credit", "full-credit"],
)
def test_rubric_scoring_rejects_invalid_thresholds_without_writes(
    db_session: Session,
    feedback_threshold: float,
    remediation_threshold: float,
    message: str,
    points: tuple[int, int],
) -> None:
    """Rejected thresholds leave no durable scoring side effects, even without rollback."""
    attempt_id = _attempt(db_session)
    rubric_id, criterion_ids = _rubric(db_session)
    criterion_scores = [
        {"criterion_id": criterion_ids[0], "points": 2},
        {"criterion_id": criterion_ids[1], "points": 3},
    ]
    db_session.commit()
    tables = [
        model.__table__
        for model in (
            EvidenceRecord,
            RubricScore,
            FeedbackRecord,
            FeedbackAction,
            ReviewQueueItem,
            ReviewCardState,
        )
    ]
    before = [db_session.scalar(select(func.count()).select_from(table)) for table in tables]

    with pytest.raises(InvalidRubricScoringError) as exc_info:
        score_attempt_with_rubric(
            db_session,
            rubric_id=rubric_id,
            attempt_id=attempt_id,
            scorer_type="human",
            criterion_scores=[
                {"criterion_id": criterion_ids[0], "points": points[0]},
                {"criterion_id": criterion_ids[1], "points": points[1]},
            ],
            feedback_threshold=feedback_threshold,
            remediation_threshold=remediation_threshold,
        )
    assert str(exc_info.value) == message
    assert exc_info.value.http_status == 422
    db_session.commit()
    assert [
        db_session.scalar(select(func.count()).select_from(table)) for table in tables
    ] == before

    # The same attempt can still be scored correctly in the same session.
    score = score_attempt_with_rubric(
        db_session,
        rubric_id=rubric_id,
        attempt_id=attempt_id,
        scorer_type="human",
        criterion_scores=criterion_scores,
    )
    db_session.commit()
    assert score.normalized_score == 1.0
    assert score.feedback_record_id is None
    assert score.evidence_record_id is not None
    evidence = get_evidence_record(db_session, score.evidence_record_id)
    assert evidence is not None
    assert evidence.correctness is True


@pytest.mark.parametrize(
    ("feedback_threshold", "remediation_threshold", "message"),
    [
        (value, 0.5, "feedback_threshold must be a finite number between 0.0 and 1.0")
        for value in [math.nan, math.inf, -math.inf, -0.1, 1.1]
    ]
    + [
        (0.85, value, "remediation_threshold must be a finite number between 0.0 and 1.0")
        for value in [math.nan, math.inf, -math.inf, -0.1, 1.1]
    ]
    + [
        (0.4, 0.8, "remediation_threshold cannot exceed feedback_threshold"),
    ]
    + [
        # Report the feedback error first for every pairing of invalid values,
        # including cases where a premature ordering check would also fail.
        (feedback, remediation, "feedback_threshold must be a finite number between 0.0 and 1.0")
        for feedback in [math.nan, math.inf, -math.inf, -0.1, 1.1]
        for remediation in [math.nan, math.inf, -math.inf, -0.1, 1.1]
    ],
)
def test_invalid_thresholds_are_rejected_before_database_access(
    feedback_threshold: float, remediation_threshold: float, message: str
) -> None:
    """Invalid configuration must fail before a lookup can trigger ORM autoflush."""
    session = Mock(spec=Session)

    with pytest.raises(InvalidRubricScoringError) as exc_info:
        score_attempt_with_rubric(
            session,
            rubric_id="unused-rubric",
            attempt_id="unused-attempt",
            scorer_type="human",
            criterion_scores=[],
            feedback_threshold=feedback_threshold,
            remediation_threshold=remediation_threshold,
        )

    assert str(exc_info.value) == message
    assert session.mock_calls == []


@pytest.mark.parametrize(
    ("thresholds", "message"),
    [
        (
            {threshold: value},
            f"{threshold} must be a finite number between 0.0 and 1.0",
        )
        for threshold in ["feedback_threshold", "remediation_threshold"]
        for value in [math.nan, math.inf, -math.inf, -0.1, 1.1]
    ]
    + [
        ({"feedback_threshold": 0.4}, "remediation_threshold cannot exceed feedback_threshold"),
        ({"remediation_threshold": 0.9}, "remediation_threshold cannot exceed feedback_threshold"),
    ],
)
def test_rubric_scoring_validates_thresholds_with_other_threshold_defaulted(
    db_session: Session, thresholds: dict[str, float], message: str
) -> None:
    """Overriding one threshold must still validate against the other's default."""
    attempt_id = _attempt(db_session)
    rubric_id, criterion_ids = _rubric(db_session)

    with pytest.raises(InvalidRubricScoringError) as exc_info:
        score_attempt_with_rubric(
            db_session,
            rubric_id=rubric_id,
            attempt_id=attempt_id,
            scorer_type="human",
            criterion_scores=[
                {"criterion_id": criterion_ids[0], "points": 2},
                {"criterion_id": criterion_ids[1], "points": 3},
            ],
            **thresholds,
        )

    assert str(exc_info.value) == message
    assert exc_info.value.http_status == 422


@pytest.mark.parametrize(
    ("feedback_threshold", "remediation_threshold", "points", "expected_level"),
    [
        (0.0, 0.0, (0, 0), None),
        (1.0, 1.0, (2, 3), None),
        (1.0, 1.0, (1, 1), "remediation"),
        (1.0, 0.0, (1, 1), "review"),
        # Values immediately inside the unit interval remain valid thresholds.
        (math.nextafter(0.0, 1.0), 0.0, (0, 0), "review"),
        (1.0, math.nextafter(0.0, 1.0), (0, 0), "remediation"),
        (math.nextafter(1.0, 0.0), 0.5, (2, 3), None),
        (1.0, math.nextafter(1.0, 0.0), (2, 3), None),
        # Equal interior thresholds have no review-only interval.
        (0.4, 0.4, (1, 0), "remediation"),
        (0.4, 0.4, (1, 1), None),
        (0.4, 0.4, (2, 2), None),
        (0.8, 0.4, (2, 2), None),
        (0.8, 0.4, (1, 1), "review"),
        (0.8, 0.4, (1, 0), "remediation"),
        (math.nextafter(0.8, 0.0), 0.4, (2, 2), None),
        (math.nextafter(0.8, 1.0), 0.4, (2, 2), "review"),
        (0.8, math.nextafter(0.4, 0.0), (1, 1), "review"),
        (0.8, math.nextafter(0.4, 1.0), (1, 1), "remediation"),
    ],
)
def test_rubric_scoring_accepts_threshold_boundaries(
    db_session: Session,
    feedback_threshold: float,
    remediation_threshold: float,
    points: tuple[int, int],
    expected_level: str | None,
) -> None:
    """Inclusive and equal thresholds preserve correctness and feedback boundaries."""
    attempt_id = _attempt(db_session)
    rubric_id, criterion_ids = _rubric(db_session)
    score = score_attempt_with_rubric(
        db_session,
        rubric_id=rubric_id,
        attempt_id=attempt_id,
        scorer_type="human",
        criterion_scores=[
            {"criterion_id": criterion_ids[0], "points": points[0]},
            {"criterion_id": criterion_ids[1], "points": points[1]},
        ],
        feedback_threshold=feedback_threshold,
        remediation_threshold=remediation_threshold,
    )
    db_session.commit()
    assert score.evidence_record_id is not None
    evidence = get_evidence_record(db_session, score.evidence_record_id)
    assert evidence is not None
    assert evidence.correctness is (expected_level is None)
    if expected_level is None:
        assert score.feedback_record_id is None
    else:
        assert score.feedback_record_id is not None
        feedback = get_feedback_record(db_session, score.feedback_record_id)
        assert feedback is not None
        assert feedback.feedback_level == expected_level
        actions = list_feedback_actions(
            db_session,
            learner_id="learner-1",
            feedback_record_id=feedback.id,
        )
        assert len(actions) == 1
        assert actions[0].action_type == (
            "prerequisite-remediation" if expected_level == "remediation" else "revision"
        )
        assert feedback.next_action_ids == [actions[0].id]


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


@pytest.mark.parametrize(
    "points", [float("nan"), float("inf"), float("-inf"), "NaN", "Infinity", "-Infinity", "1e999"]
)
def test_score_rubric_rejects_nan_and_inf_points(db_session: Session, points: object) -> None:
    """Non-finite points fail before evidence persistence and leave scoring usable."""
    attempt_id = _attempt(db_session)
    rubric_id, criterion_ids = _rubric(db_session)

    with pytest.raises(InvalidRubricScoringError, match="must be a finite number"):
        score_attempt_with_rubric(
            db_session,
            rubric_id=rubric_id,
            attempt_id=attempt_id,
            scorer_type="human",
            criterion_scores=[
                {"criterion_id": criterion_ids[0], "points": points},
                {"criterion_id": criterion_ids[1], "points": 2},
            ],
        )

    # No rollback: rejection must leave the transaction usable for a corrected score.
    score = score_attempt_with_rubric(
        db_session,
        rubric_id=rubric_id,
        attempt_id=attempt_id,
        scorer_type="human",
        criterion_scores=[
            {"criterion_id": criterion_ids[0], "points": "1.5"},
            {"criterion_id": criterion_ids[1], "points": 2},
        ],
    )
    db_session.commit()
    assert score.raw_score == 3.5
    assert score.normalized_score == 0.7


@pytest.mark.parametrize("points", ["not-a-number", "", None, [], {}, 10**400])
def test_score_rubric_rejects_non_numeric_points(db_session: Session, points: object) -> None:
    """Malformed points surface the scoring API's validation error type."""
    attempt_id = _attempt(db_session)
    rubric_id, criterion_ids = _rubric(db_session)

    with pytest.raises(InvalidRubricScoringError, match="must be a finite number") as exc_info:
        score_attempt_with_rubric(
            db_session,
            rubric_id=rubric_id,
            attempt_id=attempt_id,
            scorer_type="human",
            criterion_scores=[
                {"criterion_id": criterion_ids[0], "points": points},
                {"criterion_id": criterion_ids[1], "points": 2},
            ],
        )
    assert isinstance(exc_info.value.__cause__, (ValueError, TypeError, OverflowError))


def test_points_out_of_range_rejected(db_session: Session) -> None:
    """Points above a criterion's max_points raise (guards the max_points range check)."""
    attempt_id = _attempt(db_session)
    rubric_id, criterion_ids = _rubric(db_session)

    # criterion_ids[0] has max_points=2; 3 is out of range.
    with pytest.raises(InvalidRubricScoringError, match="within criterion max_points"):
        score_attempt_with_rubric(
            db_session,
            rubric_id=rubric_id,
            attempt_id=attempt_id,
            scorer_type="human",
            criterion_scores=[
                {"criterion_id": criterion_ids[0], "points": 3},
                {"criterion_id": criterion_ids[1], "points": 2},
            ],
        )


def test_negative_points_rejected(db_session: Session) -> None:
    """Negative points raise rather than being recorded (guards the non-negative points check)."""
    attempt_id = _attempt(db_session)
    rubric_id, criterion_ids = _rubric(db_session)

    with pytest.raises(InvalidRubricScoringError, match="within criterion max_points"):
        score_attempt_with_rubric(
            db_session,
            rubric_id=rubric_id,
            attempt_id=attempt_id,
            scorer_type="human",
            criterion_scores=[
                {"criterion_id": criterion_ids[0], "points": -1},
                {"criterion_id": criterion_ids[1], "points": 2},
            ],
        )


def test_duplicate_criterion_rejected(db_session: Session) -> None:
    """Repeating a criterion id raises before scores are doubled-counted."""
    attempt_id = _attempt(db_session)
    rubric_id, criterion_ids = _rubric(db_session)

    with pytest.raises(InvalidRubricScoringError, match="duplicate criterion ids"):
        score_attempt_with_rubric(
            db_session,
            rubric_id=rubric_id,
            attempt_id=attempt_id,
            scorer_type="human",
            criterion_scores=[
                {"criterion_id": criterion_ids[0], "points": 2},
                {"criterion_id": criterion_ids[0], "points": 1},
            ],
        )


def test_unknown_attempt_raises_attempt_not_found(db_session: Session) -> None:
    """A missing attempt id surfaces a 404-mapped AttemptNotFoundError."""
    rubric_id, criterion_ids = _rubric(db_session)

    with pytest.raises(AttemptNotFoundError) as excinfo:
        score_attempt_with_rubric(
            db_session,
            rubric_id=rubric_id,
            attempt_id="missing-attempt",
            scorer_type="human",
            criterion_scores=[
                {"criterion_id": criterion_ids[0], "points": 2},
                {"criterion_id": criterion_ids[1], "points": 2},
            ],
        )
    assert excinfo.value.http_status == 404


def test_unknown_rubric_raises_rubric_not_found(db_session: Session) -> None:
    """A missing rubric id surfaces a 404-mapped RubricNotFoundError."""
    attempt_id = _attempt(db_session)

    with pytest.raises(RubricNotFoundError) as excinfo:
        score_attempt_with_rubric(
            db_session,
            rubric_id="missing-rubric",
            attempt_id=attempt_id,
            scorer_type="human",
            criterion_scores=[
                {"criterion_id": "anything", "points": 1},
            ],
        )
    assert excinfo.value.http_status == 404


def test_rubric_score_retry_is_refused_as_duplicate(db_session: Session) -> None:
    """A second score for the same attempt+rubric is a 409, not a duplicate write.

    Audit LMS-R4: HTTP retries and double-submits used to duplicate evidence,
    review queue items, and rubric scores, inflating mastery signals.
    """
    from lms.evidence.models import EvidenceRecord
    from lms.feedback.scoring import DuplicateRubricScoreError

    attempt_id = _attempt(db_session)
    rubric_id, criterion_ids = _rubric(db_session)
    criterion_scores = [
        {"criterion_id": criterion_ids[0], "points": 2, "rationale": "Clear step."},
        {"criterion_id": criterion_ids[1], "points": 2, "rationale": "Solid."},
    ]

    score_attempt_with_rubric(
        db_session,
        rubric_id=rubric_id,
        attempt_id=attempt_id,
        scorer_type="human",
        criterion_scores=criterion_scores,
    )

    with pytest.raises(DuplicateRubricScoreError) as excinfo:
        score_attempt_with_rubric(
            db_session,
            rubric_id=rubric_id,
            attempt_id=attempt_id,
            scorer_type="human",
            criterion_scores=criterion_scores,
        )
    assert excinfo.value.http_status == 409

    evidence_rows = list(
        db_session.scalars(select(EvidenceRecord).where(EvidenceRecord.attempt_id == attempt_id))
    )
    assert len(evidence_rows) == 1, "the refused retry must not write more evidence"
