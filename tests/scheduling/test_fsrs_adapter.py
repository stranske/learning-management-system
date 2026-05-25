"""Tests for the EvidenceRecord to FSRS rating adapter."""

from __future__ import annotations

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


def test_partial_credit_boundaries(db_session: Session) -> None:
    again = create_evidence_record(
        db_session,
        learner_id="learner-1",
        knowledge_node_id="node-1",
        correctness=True,
        normalized_score=0.49,
    )
    hard = create_evidence_record(
        db_session,
        learner_id="learner-1",
        knowledge_node_id="node-1",
        correctness=True,
        normalized_score=0.84,
    )
    good = create_evidence_record(
        db_session,
        learner_id="learner-1",
        knowledge_node_id="node-1",
        correctness=True,
        normalized_score=0.85,
        confidence_rating=3,
    )

    assert evidence_to_fsrs_rating(again).label == "again"
    assert evidence_to_fsrs_rating(again).rule_id == "partial-under-half"
    assert evidence_to_fsrs_rating(hard).label == "hard"
    assert evidence_to_fsrs_rating(hard).rule_id == "partial-under-mastery"
    assert evidence_to_fsrs_rating(good).label == "good"


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


def test_adapter_rule_table_is_data_driven() -> None:
    assert [rule.rule_id for rule in FSRS_RULES] == [
        "transfer-excluded",
        "partial-under-half",
        "partial-under-mastery",
        "incorrect",
        "supported-or-low-confidence-correct",
        "fast-first-attempt",
        "unsupported-correct",
    ]
