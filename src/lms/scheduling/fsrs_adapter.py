"""Pure adapter from evidence records to FSRS-style ratings."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

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


RULE_TABLE = (
    ("transfer-distance", "exclude when transfer evidence is not near/direct"),
    ("incorrect", "map incorrect evidence to Again"),
    ("partial-credit-low", "normalized score below 0.5 maps to Again"),
    ("partial-credit-mid", "normalized score below 0.85 maps to Hard"),
    ("supported-correct", "correct with support, reference, hint, or low confidence maps to Hard"),
    (
        "first-fast-high-confidence",
        "first fast high-confidence unsupported correct response maps to Easy",
    ),
    ("unsupported-correct", "unsupported medium+ confidence correct response maps to Good"),
)

TRANSFER_EXCLUDED_VALUES = {"medium", "far", "novel", "remote"}


def evidence_to_fsrs_rating(record: EvidenceRecord) -> FSRSAdapterResult:
    """Map one evidence record to an FSRS rating or exclusion."""
    if record.transfer_distance in TRANSFER_EXCLUDED_VALUES:
        return FSRSAdapterResult(
            rating=None,
            excluded_from_scheduling=True,
            reason="transfer evidence is preserved but excluded from FSRS interval scheduling",
        )

    if record.correctness is False:
        return FSRSAdapterResult(FSRSRating.AGAIN)

    if record.normalized_score is not None:
        if record.normalized_score < 0.5:
            return FSRSAdapterResult(FSRSRating.AGAIN)
        if record.normalized_score < 0.85:
            return FSRSAdapterResult(FSRSRating.HARD)

    if _uses_support(record) or _low_confidence(record):
        return FSRSAdapterResult(FSRSRating.HARD)

    if _is_easy_first_attempt(record):
        return FSRSAdapterResult(FSRSRating.EASY)

    return FSRSAdapterResult(FSRSRating.GOOD)


def _uses_support(record: EvidenceRecord) -> bool:
    return record.hint_used or record.reference_accessed or record.support_level != "none"


def _low_confidence(record: EvidenceRecord) -> bool:
    return record.confidence_rating is not None and record.confidence_rating < 3


def _is_easy_first_attempt(record: EvidenceRecord) -> bool:
    return (
        record.confidence_rating is not None
        and record.confidence_rating >= 5
        and not _uses_support(record)
        and record.time_since_last_attempt_seconds is None
        and record.response_time_seconds is not None
        and record.response_time_seconds <= 30
    )
