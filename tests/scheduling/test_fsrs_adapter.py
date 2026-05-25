"""Tests for EvidenceRecord to FSRS rating adapter."""

from __future__ import annotations

from lms.evidence.models import EvidenceRecord
from lms.scheduling.fsrs_adapter import FSRSEvidence, FSRSRating, evidence_to_fsrs_rating


def _record(**overrides: object) -> EvidenceRecord:
    values = {
        "learner_id": "learner-1",
        "knowledge_node_id": "node-1",
        "prompt_id": "prompt-1",
        "demand_level": "recall",
        "knowledge_type": "factual",
        "correctness": True,
        "confidence_rating": 4,
        "hint_used": False,
        "reference_accessed": False,
        "support_level": "none",
        "response_time_seconds": 45,
    }
    values.update(overrides)
    return EvidenceRecord(**values)


def test_incorrect_maps_to_again() -> None:
    result = evidence_to_fsrs_rating(_record(correctness=False))

    assert result.rating == FSRSRating.AGAIN
    assert result.excluded_from_scheduling is False


def test_supported_correct_maps_to_hard() -> None:
    result = evidence_to_fsrs_rating(
        _record(correctness=True, reference_accessed=True, support_level="reference")
    )

    assert result.rating == FSRSRating.HARD


def test_partial_credit_boundaries() -> None:
    assert evidence_to_fsrs_rating(_record(normalized_score=0.49)).rating == FSRSRating.AGAIN
    assert evidence_to_fsrs_rating(_record(normalized_score=0.5)).rating == FSRSRating.HARD
    assert evidence_to_fsrs_rating(_record(normalized_score=0.84)).rating == FSRSRating.HARD
    assert evidence_to_fsrs_rating(_record(normalized_score=0.85)).rating == FSRSRating.GOOD


def test_transfer_evidence_is_excluded_from_fsrs_scheduling() -> None:
    result = evidence_to_fsrs_rating(_record(transfer_distance="far"))

    assert result.rating is None
    assert result.excluded_from_scheduling is True


def test_first_attempt_high_confidence_fast_response_maps_to_easy() -> None:
    result = evidence_to_fsrs_rating(
        _record(confidence_rating=5, time_since_last_attempt_seconds=None, response_time_seconds=20)
    )

    assert result.rating == FSRSRating.EASY


def test_unsupported_correct_maps_to_good() -> None:
    result = evidence_to_fsrs_rating(
        _record(correctness=True, confidence_rating=4, support_level="none")
    )

    assert result.rating == FSRSRating.GOOD


def test_low_confidence_correct_maps_to_hard() -> None:
    result = evidence_to_fsrs_rating(_record(correctness=True, confidence_rating=2))

    assert result.rating == FSRSRating.HARD


def test_pure_evidence_input_maps_without_sqlalchemy_model() -> None:
    result = evidence_to_fsrs_rating(
        FSRSEvidence(
            correctness=True,
            confidence_rating=5,
            hint_used=False,
            reference_accessed=False,
            support_level="none",
            response_time_seconds=20,
            time_since_last_attempt_seconds=None,
            normalized_score=None,
            transfer_distance=None,
        )
    )

    assert result.rating == FSRSRating.EASY
