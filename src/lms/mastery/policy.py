"""Mastery estimator policy adapters."""

from __future__ import annotations

from dataclasses import dataclass

from lms.evidence.models import EvidenceRecord
from lms.evidence.scoring import record_score


@dataclass(frozen=True)
class MasteryEstimatorPolicy:
    """Lightweight FSRS-compatible placeholder over evidence history."""

    estimator_version: str = "fsrs-4.5-placeholder-v2"
    model_attribution: str = "Deterministic placeholder policy inspired by FSRS 4.5"

    def estimate(self, records: list[EvidenceRecord]) -> tuple[float, float]:
        """Return mastery and a heuristic confidence in demonstrated mastery.

        Confidence combines capped evidence volume with the recency-weighted
        score: volume * (0.5 + 0.5 * mastery). Repeated weak performance therefore
        cannot earn the same confidence as strong performance at the same count.
        This is a placeholder signal, not a calibrated probability or FSRS model.
        """
        if not records:
            return 0.0, 0.0
        weighted_score = 0.0
        total_weight = 0.0
        for index, record in enumerate(records):
            weight = 1.0 + index * 0.15
            score = record_score(record)
            weighted_score += score * weight
            total_weight += weight
        mastery = weighted_score / total_weight
        volume = min(1.0, 0.35 + len(records) * 0.12)
        confidence = volume * (0.5 + 0.5 * mastery)
        return round(mastery, 4), round(confidence, 4)
