"""Map evidence records to deterministic FSRS-style ratings."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from lms.evidence.models import EvidenceRecord


@dataclass(frozen=True)
class FSRSRating:
    """A scheduler-ready rating decision for one evidence record."""

    label: str
    value: int | None
    scheduling_included: bool
    rule_id: str
    reason: str


@dataclass(frozen=True)
class FSRSRule:
    """Data-driven rule row for the v1 placeholder adapter."""

    rule_id: str
    rating: str
    value: int | None
    scheduling_included: bool
    reason: str
    applies: Callable[[EvidenceRecord], bool]


TRANSFER_EXCLUDED_DISTANCES = frozenset({"near", "far", "novel"})
LOW_CONFIDENCE_MAX = 2
MEDIUM_CONFIDENCE_MIN = 3
HIGH_CONFIDENCE_MIN = 5
FAST_FIRST_ATTEMPT_SECONDS = 30
SUPPORTED_LEVELS = frozenset(
    {
        "hint",
        "reference",
        "worked-example",
        "coach",
    }
)


def _score(record: EvidenceRecord) -> float | None:
    """Normalize explicit score signals before boolean correctness rules."""
    if record.normalized_score is not None:
        return record.normalized_score
    if record.raw_score is not None and record.max_score:
        return record.raw_score / record.max_score
    return None


def _has_support(record: EvidenceRecord) -> bool:
    support_level = (record.support_level or "").strip().lower()
    return record.hint_used or record.reference_accessed or support_level in SUPPORTED_LEVELS


def _is_supported_correct_or_low_confidence(record: EvidenceRecord) -> bool:
    if record.correctness is not True:
        return False
    return _has_support(record) or (
        record.confidence_rating is not None and record.confidence_rating <= LOW_CONFIDENCE_MAX
    )


def _is_fast_first_attempt(record: EvidenceRecord) -> bool:
    """Return true for explicitly first-attempt, fast, high-confidence correctness."""

    attempt_context = record.attempt_context or {}
    attempt_number = attempt_context.get("attempt_number")
    is_first_attempt = (
        attempt_number == 1
        if isinstance(attempt_number, int)
        else record.time_since_last_attempt_seconds is None
    )

    return (
        record.correctness is True
        and not _has_support(record)
        and (record.confidence_rating or 0) >= HIGH_CONFIDENCE_MIN
        and record.response_time_seconds is not None
        and record.response_time_seconds <= FAST_FIRST_ATTEMPT_SECONDS
        and is_first_attempt
    )


def _is_good_unsupported_correct(record: EvidenceRecord) -> bool:
    return (
        record.correctness is True
        and not _has_support(record)
        and record.confidence_rating is not None
        and record.confidence_rating >= MEDIUM_CONFIDENCE_MIN
    )


def _is_score_under_half(record: EvidenceRecord) -> bool:
    score = _score(record)
    return record.correctness is True and score is not None and score < 0.5


def _is_score_under_mastery(record: EvidenceRecord) -> bool:
    score = _score(record)
    return record.correctness is True and score is not None and 0.5 <= score < 0.85


def _is_score_at_mastery(record: EvidenceRecord) -> bool:
    score = _score(record)
    return record.correctness is not False and score is not None and score >= 0.85


FSRS_RULES: tuple[FSRSRule, ...] = (
    FSRSRule(
        rule_id="transfer-excluded",
        rating="excluded",
        value=None,
        scheduling_included=False,
        reason="Transfer evidence is retained but excluded from FSRS interval calculation.",
        applies=lambda record: (
            (record.transfer_distance or "").strip().lower() in TRANSFER_EXCLUDED_DISTANCES
        ),
    ),
    FSRSRule(
        rule_id="partial-under-half",
        rating="again",
        value=1,
        scheduling_included=True,
        reason="Normalized or partial-credit score is below the 0.5 retrieval threshold.",
        applies=_is_score_under_half,
    ),
    FSRSRule(
        rule_id="partial-under-mastery",
        rating="hard",
        value=2,
        scheduling_included=True,
        reason="Normalized or partial-credit score is below the 0.85 mastery threshold.",
        applies=_is_score_under_mastery,
    ),
    FSRSRule(
        rule_id="partial-at-mastery",
        rating="good",
        value=3,
        scheduling_included=True,
        reason="Normalized or partial-credit score meets the 0.85 mastery threshold.",
        applies=_is_score_at_mastery,
    ),
    FSRSRule(
        rule_id="incorrect",
        rating="again",
        value=1,
        scheduling_included=True,
        reason="Incorrect evidence maps to FSRS Again.",
        applies=lambda record: record.correctness is False,
    ),
    FSRSRule(
        rule_id="supported-or-low-confidence-correct",
        rating="hard",
        value=2,
        scheduling_included=True,
        reason="Correct evidence with support or low confidence maps to FSRS Hard.",
        applies=_is_supported_correct_or_low_confidence,
    ),
    FSRSRule(
        rule_id="fast-first-attempt",
        rating="easy",
        value=4,
        scheduling_included=True,
        reason="Fast high-confidence first-attempt correctness maps to FSRS Easy.",
        applies=_is_fast_first_attempt,
    ),
    FSRSRule(
        rule_id="unsupported-correct",
        rating="good",
        value=3,
        scheduling_included=True,
        reason="Unsupported medium-or-higher confidence correctness maps to FSRS Good.",
        applies=_is_good_unsupported_correct,
    ),
)


def evidence_to_fsrs_rating(record: EvidenceRecord) -> FSRSRating:
    """Return the first matching deterministic FSRS-style rating for evidence."""
    for rule in FSRS_RULES:
        if rule.applies(record):
            return FSRSRating(
                label=rule.rating,
                value=rule.value,
                scheduling_included=rule.scheduling_included,
                rule_id=rule.rule_id,
                reason=rule.reason,
            )
    return FSRSRating(
        label="again",
        value=1,
        scheduling_included=True,
        rule_id="insufficient-signal",
        reason="Evidence lacks enough positive correctness signal; schedule conservatively.",
    )
