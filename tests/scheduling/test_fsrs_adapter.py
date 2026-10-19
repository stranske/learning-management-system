"""Tests for the EvidenceRecord to FSRS rating adapter."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from lms.evidence.models import EvidenceRecord
from lms.evidence.repository import create_evidence_record
from lms.scheduling.fsrs_adapter import FSRS_RULES, _score, evidence_to_fsrs_rating


def test_incorrect_maps_to_again(db_session: Session) -> None:
    record = create_evidence_record(
        db_session,
        learner_id="learner-1",
        knowledge_node_id="node-1",
        correctness=False,
    )

    rating = evidence_to_fsrs_rating(record)

    assert rating.label == "again"
    assert rating.value == 1
    assert rating.scheduling_included is True
    assert rating.rule_id == "incorrect"


def test_supported_correct_maps_to_hard(db_session: Session) -> None:
    record = create_evidence_record(
        db_session,
        learner_id="learner-1",
        knowledge_node_id="node-1",
        correctness=True,
        confidence_rating=5,
        support_level="hint",
        hint_used=True,
    )

    rating = evidence_to_fsrs_rating(record)

    assert rating.label == "hard"
    assert rating.value == 2
    assert rating.scheduling_included is True
    assert rating.rule_id == "supported-or-low-confidence-correct"


def test_supported_high_score_is_hard(db_session: Session) -> None:
    record = create_evidence_record(
        db_session,
        learner_id="learner-1",
        knowledge_node_id="node-1",
        correctness=True,
        support_level="hint",
        hint_used=True,
        normalized_score=0.95,
    )

    rating = evidence_to_fsrs_rating(record)

    assert rating.label == "hard"
    assert rating.value == 2
    assert rating.scheduling_included is True
    assert rating.rule_id == "supported-or-low-confidence-correct"


def test_reference_accessed_maps_to_hard_even_without_support_level(db_session: Session) -> None:
    record = create_evidence_record(
        db_session,
        learner_id="learner-1",
        knowledge_node_id="node-1",
        correctness=True,
        confidence_rating=5,
        support_level="none",
        hint_used=False,
        reference_accessed=True,
    )

    rating = evidence_to_fsrs_rating(record)

    assert rating.label == "hard"
    assert rating.value == 2
    assert rating.rule_id == "supported-or-low-confidence-correct"


def test_low_confidence_unsupported_correct_maps_to_hard(db_session: Session) -> None:
    record = create_evidence_record(
        db_session,
        learner_id="learner-1",
        knowledge_node_id="node-1",
        correctness=True,
        confidence_rating=2,
        support_level="none",
        hint_used=False,
        reference_accessed=False,
    )

    rating = evidence_to_fsrs_rating(record)

    assert rating.label == "hard"
    assert rating.value == 2
    assert rating.scheduling_included is True
    assert rating.rule_id == "supported-or-low-confidence-correct"


def test_low_confidence_high_score_is_hard(db_session: Session) -> None:
    record = create_evidence_record(
        db_session,
        learner_id="learner-1",
        knowledge_node_id="node-1",
        correctness=True,
        confidence_rating=2,
        support_level="none",
        hint_used=False,
        reference_accessed=False,
        normalized_score=0.95,
    )

    rating = evidence_to_fsrs_rating(record)

    assert rating.label == "hard"
    assert rating.value == 2
    assert rating.scheduling_included is True
    assert rating.rule_id == "supported-or-low-confidence-correct"


def _self_grade_partial_record(
    db_session: Session,
    *,
    normalized_score: float,
    confidence_rating: int = 5,
) -> EvidenceRecord:
    """Build evidence from the real UI partial self-grade shape in attempts.py."""
    from lms.ui.attempts import _SELF_GRADES

    grade = dict(_SELF_GRADES["partial"])
    # Pin the contract the adapter must honor: unspecified correctness and
    # partial-credit scoring, with only the normalized score under test varying.
    assert grade["correctness"] is None
    assert grade["scoring_method"] == "partial-credit"
    grade["normalized_score"] = normalized_score
    return create_evidence_record(
        db_session,
        learner_id="learner-1",
        knowledge_node_id="node-1",
        confidence_rating=confidence_rating,
        **grade,
    )


@pytest.mark.parametrize(
    ("score", "expected_label", "expected_value", "expected_rule_id"),
    [
        (0.30, "again", 1, "partial-under-half"),
        (0.70, "hard", 2, "partial-under-mastery"),
        (0.90, "good", 3, "partial-at-mastery"),
    ],
    ids=["representative-under-half", "representative-under-mastery", "representative-at-mastery"],
)
def test_partial_credit_representative_cases(
    db_session: Session,
    score: float,
    expected_label: str,
    expected_value: int,
    expected_rule_id: str,
) -> None:
    record = _self_grade_partial_record(db_session, normalized_score=score)
    rating = evidence_to_fsrs_rating(record)
    assert record.correctness is None
    assert record.scoring_method == "partial-credit"
    assert rating.label == expected_label
    assert rating.value == expected_value
    assert rating.rule_id == expected_rule_id


@pytest.mark.parametrize(
    ("score", "expected_label", "expected_value", "expected_rule_id"),
    [
        (0.49, "again", 1, "partial-under-half"),
        (0.50, "hard", 2, "partial-under-mastery"),
    ],
    ids=["under-half-upper-boundary", "under-mastery-lower-boundary"],
)
def test_partial_credit_half_threshold_boundary(
    db_session: Session,
    score: float,
    expected_label: str,
    expected_value: int,
    expected_rule_id: str,
) -> None:
    record = _self_grade_partial_record(db_session, normalized_score=score)
    rating = evidence_to_fsrs_rating(record)
    assert record.correctness is None
    assert rating.label == expected_label
    assert rating.value == expected_value
    assert rating.rule_id == expected_rule_id


@pytest.mark.parametrize(
    ("score", "expected_label", "expected_value", "expected_rule_id"),
    [
        (0.84, "hard", 2, "partial-under-mastery"),
        (0.85, "good", 3, "partial-at-mastery"),
    ],
    ids=["under-mastery-upper-boundary", "at-mastery-lower-boundary"],
)
def test_partial_credit_mastery_threshold_boundary(
    db_session: Session,
    score: float,
    expected_label: str,
    expected_value: int,
    expected_rule_id: str,
) -> None:
    record = _self_grade_partial_record(db_session, normalized_score=score)
    rating = evidence_to_fsrs_rating(record)
    assert record.correctness is None
    assert rating.label == expected_label
    assert rating.value == expected_value
    assert rating.rule_id == expected_rule_id


def test_canonical_ui_partial_self_grade_maps_to_hard(db_session: Session) -> None:
    """The exact UI partial payload (score 0.7, correctness=None) is Hard."""
    from lms.ui.attempts import _SELF_GRADES

    record = create_evidence_record(
        db_session,
        learner_id="learner-1",
        knowledge_node_id="node-1",
        confidence_rating=5,
        **_SELF_GRADES["partial"],
    )
    rating = evidence_to_fsrs_rating(record)
    assert record.correctness is None
    assert record.normalized_score == 0.7
    assert rating.label == "hard"
    assert rating.value == 2
    assert rating.rule_id == "partial-under-mastery"


@pytest.mark.parametrize("score", [0.7, 0.85], ids=["partial", "mastery-boundary"])
@pytest.mark.parametrize(
    "confidence, support_level, hint_used, reference_accessed",
    [
        (2, "none", False, False),
        (5, "none", True, False),
        (5, "none", False, True),
        (5, "coach", False, False),
    ],
    ids=["low-confidence", "hint", "reference", "coach"],
)
def test_ui_partial_self_grade_caps_at_mastery(
    db_session: Session,
    score: float,
    confidence: int,
    support_level: str,
    hint_used: bool,
    reference_accessed: bool,
) -> None:
    """Unspecified correctness must retain caps even at the Good threshold."""
    record = _self_grade_partial_record(
        db_session, normalized_score=score, confidence_rating=confidence
    )
    record.support_level = support_level
    record.hint_used = hint_used
    record.reference_accessed = reference_accessed
    record.response_time_seconds = 20

    rating = evidence_to_fsrs_rating(record, prompt_class_median_seconds=20)

    assert rating.label == "hard"
    assert rating.value == 2
    assert rating.rule_id == "supported-or-low-confidence-correct"
    assert rating.scheduling_included is True


def test_mastery_score_without_correctness_maps_to_good(db_session: Session) -> None:
    record = create_evidence_record(
        db_session,
        learner_id="learner-1",
        knowledge_node_id="node-1",
        correctness=None,
        normalized_score=0.85,
    )

    rating = evidence_to_fsrs_rating(record)

    assert rating.label == "good"
    assert rating.value == 3
    assert rating.scheduling_included is True
    assert rating.rule_id == "partial-at-mastery"


def test_incorrect_precedes_partial_credit_rules(db_session: Session) -> None:
    record = create_evidence_record(
        db_session,
        learner_id="learner-1",
        knowledge_node_id="node-1",
        correctness=False,
        normalized_score=0.84,
    )

    rating = evidence_to_fsrs_rating(record)

    assert rating.label == "again"
    assert rating.value == 1
    assert rating.rule_id == "incorrect"


def test_transfer_evidence_is_excluded_from_fsrs_scheduling(db_session: Session) -> None:
    record = create_evidence_record(
        db_session,
        learner_id="learner-1",
        knowledge_node_id="node-1",
        correctness=True,
        normalized_score=1.0,
        transfer_distance="near",
    )

    rating = evidence_to_fsrs_rating(record)

    assert rating.label == "excluded"
    assert rating.value is None
    assert rating.scheduling_included is False
    assert rating.rule_id == "transfer-excluded"


def test_transfer_distance_is_trimmed_and_case_insensitive(db_session: Session) -> None:
    record = create_evidence_record(
        db_session,
        learner_id="learner-1",
        knowledge_node_id="node-1",
        correctness=True,
        normalized_score=1.0,
        transfer_distance=" Near ",
    )

    rating = evidence_to_fsrs_rating(record)

    assert rating.label == "excluded"
    assert rating.value is None
    assert rating.scheduling_included is False
    assert rating.rule_id == "transfer-excluded"


def test_medium_confidence_unsupported_correct_maps_to_good(db_session: Session) -> None:
    record = create_evidence_record(
        db_session,
        learner_id="learner-1",
        knowledge_node_id="node-1",
        correctness=True,
        confidence_rating=3,
        support_level="none",
    )

    rating = evidence_to_fsrs_rating(record)

    assert rating.label == "good"
    assert rating.value == 3
    assert rating.rule_id == "unsupported-correct"


def test_unsupported_correct_without_confidence_does_not_map_to_good(db_session: Session) -> None:
    record = create_evidence_record(
        db_session,
        learner_id="learner-1",
        knowledge_node_id="node-1",
        correctness=True,
        support_level="none",
    )

    rating = evidence_to_fsrs_rating(record)

    assert rating.label == "again"
    assert rating.value == 1
    assert rating.rule_id == "insufficient-signal"


def test_fast_high_confidence_first_attempt_maps_to_easy(db_session: Session) -> None:
    record = create_evidence_record(
        db_session,
        learner_id="learner-1",
        knowledge_node_id="node-1",
        correctness=True,
        confidence_rating=5,
        response_time_seconds=12,
        support_level="none",
    )

    rating = evidence_to_fsrs_rating(record, prompt_class_median_seconds=12)

    assert rating.label == "easy"
    assert rating.value == 4
    assert rating.rule_id == "fast-first-attempt"


def test_fast_high_confidence_non_first_attempt_does_not_map_to_easy(db_session: Session) -> None:
    record = create_evidence_record(
        db_session,
        learner_id="learner-1",
        knowledge_node_id="node-1",
        correctness=True,
        confidence_rating=5,
        response_time_seconds=12,
        support_level="none",
        attempt_context={"attempt_number": 2},
    )

    rating = evidence_to_fsrs_rating(record, prompt_class_median_seconds=12)

    assert rating.label == "good"
    assert rating.value == 3
    assert rating.rule_id == "unsupported-correct"


@pytest.mark.parametrize(
    "median, seconds, first_attempt",
    [
        (None, 1, True),
        (0, 1, True),
        (-1, 1, True),
        (float("nan"), 1, True),
        (float("inf"), 1, True),
        (float("-inf"), 1, True),
        (20, None, True),
        (20, 1, False),
    ],
    ids=[
        "missing-median",
        "zero-median",
        "negative-median",
        "nan-median",
        "infinite-median",
        "negative-infinite-median",
        "missing-response-time",
        "service-detected-repeat",
    ],
)
def test_ui_binary_correct_requires_eligible_timing_context_for_easy(
    median: float | None, seconds: int | None, first_attempt: bool
) -> None:
    from lms.ui.attempts import _SELF_GRADES

    record = EvidenceRecord(
        learner_id="learner-1",
        knowledge_node_id="node-1",
        confidence_rating=5,
        response_time_seconds=seconds,
        attempt_context={"attempt_number": 1},
        **_SELF_GRADES["correct"],
    )

    rating = evidence_to_fsrs_rating(
        record, prompt_class_median_seconds=median, first_attempt=first_attempt
    )

    assert rating.label == "good"
    assert rating.value == 3
    assert rating.rule_id == "unsupported-correct"
    assert rating.scheduling_included is True


def test_partial_credit_uses_raw_score_divided_by_max_score(db_session: Session) -> None:
    record = create_evidence_record(
        db_session,
        learner_id="learner-1",
        knowledge_node_id="node-1",
        correctness=True,
        raw_score=3.0,
        max_score=4.0,
        normalized_score=None,
    )

    rating = evidence_to_fsrs_rating(record)

    assert rating.label == "hard"
    assert rating.value == 2
    assert rating.rule_id == "partial-under-mastery"


def test_low_confidence_without_true_correctness_does_not_map_to_hard(db_session: Session) -> None:
    record = create_evidence_record(
        db_session,
        learner_id="learner-1",
        knowledge_node_id="node-1",
        correctness=None,
        confidence_rating=1,
        support_level="none",
    )

    rating = evidence_to_fsrs_rating(record)

    assert rating.label == "again"
    assert rating.value == 1
    assert rating.rule_id == "insufficient-signal"


def test_adapter_rule_table_is_data_driven() -> None:
    assert [rule.rule_id for rule in FSRS_RULES] == [
        "transfer-excluded",
        "incorrect",
        "insufficient-signal",
        "supported-or-low-confidence-correct",
        "partial-under-half",
        "partial-under-mastery",
        "partial-at-mastery",
        "fast-first-attempt",
        "unsupported-correct",
    ]


@pytest.mark.parametrize("correctness", [None, True])
@pytest.mark.parametrize("confidence", [3, 5])
@pytest.mark.parametrize(
    ("normalized_score", "raw_score", "max_score"),
    [
        (float("nan"), None, None),
        (float("inf"), None, None),
        (float("-inf"), None, None),
        (None, float("nan"), 4.0),
        (None, float("inf"), 4.0),
        (None, float("-inf"), 4.0),
        (None, 3.0, float("nan")),
        (None, 3.0, float("inf")),
        (None, 3.0, float("-inf")),
        (None, 1e308, 1e-308),
    ],
    ids=[
        "normalized-nan",
        "normalized-inf",
        "normalized-negative-inf",
        "raw-nan",
        "raw-inf",
        "raw-negative-inf",
        "max-nan",
        "max-inf",
        "max-negative-inf",
        "ratio-overflow",
    ],
)
def test_non_finite_scores_schedule_conservatively(
    normalized_score: float | None,
    raw_score: float | None,
    max_score: float | None,
    correctness: bool | None,
    confidence: int,
) -> None:
    # Keep the non-finite values in memory: SQLite can coerce NaN to SQL NULL.
    record = EvidenceRecord(
        learner_id="learner-1",
        knowledge_node_id="node-1",
        normalized_score=normalized_score,
        raw_score=raw_score,
        max_score=max_score,
        correctness=correctness,
        confidence_rating=confidence,
        response_time_seconds=12,
    )

    rating = evidence_to_fsrs_rating(record)

    assert rating.label == "again"
    assert rating.value == 1
    assert rating.rule_id == "insufficient-signal"
    assert rating.scheduling_included is True
    assert _score(record) is None


@pytest.mark.parametrize("correctness", [False, True])
def test_non_finite_transfer_evidence_remains_excluded(correctness: bool) -> None:
    record = EvidenceRecord(
        learner_id="learner-1",
        knowledge_node_id="node-1",
        normalized_score=float("nan"),
        correctness=correctness,
        transfer_distance="near",
    )

    rating = evidence_to_fsrs_rating(record)

    assert rating.rule_id == "transfer-excluded"
    assert rating.scheduling_included is False
    assert rating.value is None


def test_service_honors_adapter_eligibility_before_any_card_write(db_session, monkeypatch):
    from lms.scheduling import service
    from lms.scheduling.fsrs_adapter import FSRSRating
    from lms.scheduling.models import ReviewCardState
    from tests.scheduling.test_review_queue import _make_attempt

    attempt, evidence = _make_attempt(db_session)
    monkeypatch.setattr(
        service,
        "evidence_to_fsrs_rating",
        lambda _, **context: FSRSRating(
            label="excluded",
            value=None,
            scheduling_included=False,
            rule_id="custom-exclusion",
            reason="excluded",
        ),
    )
    outcome = service.schedule_from_attempt(db_session, attempt=attempt, evidence_record=evidence)
    assert outcome.decision_log["rule"] == "custom-exclusion"
    assert outcome.due_at is None
    assert db_session.query(ReviewCardState).count() == 0


@pytest.mark.parametrize(
    "grade, median, seconds, expected",
    [
        ("correct", 20, 20, 4),
        ("correct", 20, 21, 3),
        ("correct", 10, 20, 3),
        ("correct", None, 1, 3),
        ("partial", 20, 20, 2),
        ("incorrect", 20, 20, 1),
    ],
)
def test_ui_self_grades_preserve_distinct_ratings(
    db_session: Session, grade: str, median: int | None, seconds: int, expected: int
) -> None:
    from lms.ui.attempts import _SELF_GRADES

    record = create_evidence_record(
        db_session,
        learner_id="l",
        knowledge_node_id="n",
        confidence_rating=5,
        response_time_seconds=seconds,
        **_SELF_GRADES[grade],
    )
    rating = evidence_to_fsrs_rating(record, prompt_class_median_seconds=median)
    assert rating.value == expected
    assert rating.scheduling_included is True


@pytest.mark.parametrize("correctness", [True, None])
def test_binary_mastery_without_confidence_keeps_good(db_session, correctness):
    record = create_evidence_record(
        db_session,
        learner_id="l",
        knowledge_node_id="n",
        scoring_method="binary",
        correctness=correctness,
        normalized_score=1.0,
    )
    rating = evidence_to_fsrs_rating(record)
    assert rating.value == 3
    assert rating.rule_id != "insufficient-signal"
