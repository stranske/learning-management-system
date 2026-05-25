"""Mastery estimator policy adapters."""

from __future__ import annotations

from dataclasses import dataclass

from lms.evidence.models import EvidenceRecord


@dataclass(frozen=True)
class MasteryEstimatorPolicy:
    """Lightweight FSRS-compatible placeholder over evidence history."""

    estimator_version: str = "fsrs-4.5-placeholder-v1"
    model_attribution: str = "Deterministic placeholder policy inspired by FSRS 4.5"

    def estimate(self, records: list[EvidenceRecord]) -> tuple[float, float]:
        """Return current mastery and confidence from newest-first records."""
        if not records:
            return 0.0, 0.0
        weighted_score = 0.0
        total_weight = 0.0
        for index, record in enumerate(reversed(records)):
            weight = 1.0 + index * 0.15
            score = _record_score(record)
            weighted_score += score * weight
            total_weight += weight
        mastery = weighted_score / total_weight
        confidence = min(1.0, 0.35 + len(records) * 0.12)
        return round(mastery, 4), round(confidence, 4)


def _record_score(record: EvidenceRecord) -> float:
    if record.normalized_score is not None:
        return float(record.normalized_score)
    if record.raw_score is not None and record.max_score:
        return float(record.raw_score) / float(record.max_score)
    if record.correctness is not None:
        return 1.0 if record.correctness else 0.0
    return 0.5
