"""Shared scoring helpers for evidence records."""

from __future__ import annotations

from lms.evidence.models import EvidenceRecord


def record_score(record: EvidenceRecord) -> float:
    """Map an evidence record to a 0..1 score using its best available signal.

    Falls back through normalized score, then the raw/max ratio, then binary
    correctness, defaulting to the 0.5 midpoint when no signal is present.
    """
    if record.normalized_score is not None:
        return float(record.normalized_score)
    if record.raw_score is not None and record.max_score:
        return float(record.raw_score) / float(record.max_score)
    if record.correctness is not None:
        return 1.0 if record.correctness else 0.0
    return 0.5
