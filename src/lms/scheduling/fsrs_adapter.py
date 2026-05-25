"""Pure adapter from evidence records to FSRS-style ratings."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Callable

from lms.evidence.models import EvidenceRecord


class FSRSRating(IntEnum):
    """FSRS review ratings."""

    AGAIN = 1
    HARD = 2
    GOOD = 3
    EASY = 4


@dataclass(frozen=True)
class FSRSAdapterResult:
    """Adapter output with exclusion reason for non-scheduling evidence."""

    rating: FSRSRating | None
    excluded_from_scheduling: bool = False
    reason: str | None = None


@dataclass(frozen=True)
class FSRSEvidence:
    """Pure evidence payload for mapping into an FSRS rating."""

    correctness: bool | None
    confidence_rating: int | None
    hint_used: bool
    reference_accessed: bool
    support_level: str
    response_time_seconds: int | None
    time_since_last_attempt_seconds: int | None
    normalized_score: float | None = None
    transfer_distance: str | None = None


@dataclass(frozen=True)
class RatingRule:
    """One row in the deterministic adapter rule table."""

    name: str
    matcher: Callable[[FSRSEvidence], bool]
    rating: FSRSRating

TRANSFER_EXCLUDED_VALUES = {"medium", "far", "novel", "remote"}


RULE_TABLE: tuple[RatingRule, ...] = (
    RatingRule("incorrect", lambda evidence: evidence.correctness is False, FSRSRating.AGAIN),
    RatingRule(
        "partial-credit-low",
        lambda evidence: evidence.normalized_score is not None and evidence.normalized_score < 0.5,
        FSRSRating.AGAIN,
    ),
    RatingRule(
        "partial-credit-mid",
        lambda evidence: evidence.normalized_score is not None and evidence.normalized_score < 0.85,
        FSRSRating.HARD,
    ),
    RatingRule(
        "supported-or-low-confidence-correct",
        lambda evidence: _is_supported_or_low_confidence_correct(evidence),
        FSRSRating.HARD,
    ),
    RatingRule(
        "first-fast-high-confidence-correct",
        lambda evidence: _is_easy_first_attempt(evidence),
        FSRSRating.EASY,
    ),
    RatingRule("unsupported-correct-default", lambda evidence: True, FSRSRating.GOOD),
)


def evidence_to_fsrs_rating(record: EvidenceRecord | FSRSEvidence) -> FSRSAdapterResult:
    """Map one evidence record to an FSRS rating or exclusion."""
    evidence = _coerce_evidence(record)
    if evidence.transfer_distance in TRANSFER_EXCLUDED_VALUES:
        return FSRSAdapterResult(
            rating=None,
            excluded_from_scheduling=True,
            reason="transfer evidence is preserved but excluded from FSRS interval scheduling",
        )

    for rule in RULE_TABLE:
        if rule.matcher(evidence):
            return FSRSAdapterResult(rule.rating)
    raise RuntimeError("FSRS rule table must always produce a rating")


def _coerce_evidence(record: EvidenceRecord | FSRSEvidence) -> FSRSEvidence:
    if isinstance(record, FSRSEvidence):
        return record
    return FSRSEvidence(
        correctness=record.correctness,
        confidence_rating=record.confidence_rating,
        hint_used=record.hint_used,
        reference_accessed=record.reference_accessed,
        support_level=record.support_level,
        response_time_seconds=record.response_time_seconds,
        time_since_last_attempt_seconds=record.time_since_last_attempt_seconds,
        normalized_score=record.normalized_score,
        transfer_distance=record.transfer_distance,
    )


def _uses_support(evidence: FSRSEvidence) -> bool:
    return evidence.hint_used or evidence.reference_accessed or evidence.support_level != "none"


def _low_confidence(evidence: FSRSEvidence) -> bool:
    return evidence.confidence_rating is not None and evidence.confidence_rating < 3


def _is_supported_or_low_confidence_correct(evidence: FSRSEvidence) -> bool:
    return evidence.correctness is True and (_uses_support(evidence) or _low_confidence(evidence))


def _is_easy_first_attempt(evidence: FSRSEvidence) -> bool:
    return (
        evidence.correctness is True
        and evidence.confidence_rating is not None
        and evidence.confidence_rating >= 5
        and not _uses_support(evidence)
        and evidence.time_since_last_attempt_seconds is None
        and evidence.response_time_seconds is not None
        and evidence.response_time_seconds <= 30
    )
