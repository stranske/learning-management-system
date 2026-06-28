"""Tests for the EvidenceRecord to FSRS rating adapter."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from lms.evidence.repository import create_evidence_record
from lms.scheduling.fsrs_adapter import FSRS_RULES, evidence_to_fsrs_rating


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


@pytest.mark.parametrize(
    ("score", "expected_label", "expected_rule_id"),
    [
        (0.30, "again", "partial-under-half"),
        (0.70, "hard", "partial-under-mastery"),
        (0.90, "good", "partial-at-mastery"),
    ],
    ids=["representative-under-half", "representative-under-mastery", "representative-at-mastery"]
)
def test_partial_credit_representative_cases(
    db_session: Session,
    score: float,
    expected_label: str,
    expected_rule_id: str,
) -> None:
    record = create_evidence_record(
        db_session,
        learner_id="learner-1",
        knowledge_node_id="node-1",
        correctness=True,
        normalized_score=score,
        confidence_rating=3,
    )
    rating = evidence_to_fsrs_rating(record)
    assert rating.label == expected_label
    assert rating.rule_id == expected_rule_id


@pytest.mark.parametrize(
    ("score", "expected_label", "expected_rule_id"),
    [
        (0.49, "again", "partial-under-half"),
        (0.50, "hard", "partial-under-mastery"),
    ],
    ids=["under-half-upper-boundary", "under-mastery-lower-boundary"]
)
def test_partial_credit_half_threshold_boundary(
    db_session: Session,
    score: float,
    expected_label: str,
    expected_rule_id: str,
) -> None:
    record = create_evidence_record(
        db_session,
        learner_id="learner-1",
        knowledge_node_id="node-1",
        correctness=True,
        normalized_score=score,
        confidence_rating=3,
    )
    rating = evidence_to_fsrs_rating(record)
    assert rating.label == expected_label
    assert rating.rule_id == expected_rule_id


@pytest.mark.parametrize(
    ("score", "expected_label", "expected_rule_id"),
    [
        (0.84, "hard", "partial-under-mastery"),
        (0.85, "good", "partial-at-mastery"),
    ],
    ids=["under-mastery-upper-boundary", "at-mastery-lower-boundary"]
)
def test_partial_credit_mastery_threshold_boundary(
    db_session: Session,
    score: float,
    expected_label: str,
    expected_rule_id: str,
) -> None:
    record = create_evidence_record(
        db_session,
        learner_id="learner-1",
        knowledge_node_id="node-1",
        correctness=True,
        normalized_score=score,
        confidence_rating=3,
    )
    rating = evidence_to_fsrs_rating(record)
    assert rating.label == expected_label
    assert rating.rule_id == expected_rule_id


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

    rating = evidence_to_fsrs_rating(record)

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

    rating = evidence_to_fsrs_rating(record)

    assert rating.label == "good"
    assert rating.value == 3
    assert rating.rule_id == "unsupported-correct"


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
        "supported-or-low-confidence-correct",
        "partial-under-half",
        "partial-under-mastery",
        "partial-at-mastery",
        "fast-first-attempt",
        "unsupported-correct",
    ]
