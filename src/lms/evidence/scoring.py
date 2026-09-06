"""Shared scoring helpers for evidence records."""

from __future__ import annotations

from math import isfinite

from lms.evidence.models import EvidenceRecord


def record_score(record: EvidenceRecord) -> float:
    """Map an evidence record to a 0..1 score using its best available signal.

    Falls back through normalized score, then the raw/max ratio, then binary
    correctness, defaulting to the 0.5 midpoint when no signal is present.
    """
    score = resolved_normalized_score(
        normalized_score=record.normalized_score,
        raw_score=record.raw_score,
        max_score=record.max_score,
    )
    if score is not None:
        return score
    if record.correctness is not None:
        return 1.0 if record.correctness else 0.0
    return 0.5


def resolved_normalized_score(
    *, normalized_score: float | None, raw_score: float | None, max_score: float | None
) -> float | None:
    """Select a finite normalized score or raw/max ratio, ignoring invalid signals."""
    if normalized_score is not None and isfinite(normalized_score):
        return float(normalized_score)
    if (
        raw_score is not None
        and isfinite(raw_score)
        and max_score is not None
        and isfinite(max_score)
        and max_score != 0
    ):
        ratio = raw_score / max_score
        if isfinite(ratio):
            return ratio
    return None
