"""Mastery estimator policy adapters."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from lms.evidence.models import EvidenceRecord
from lms.evidence.scoring import record_score

_RETENTION_HALF_LIFE_DAYS = 30.0


def _to_utc(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)


def _retention_decay_factor(*, latest_observed_at: datetime, as_of: datetime) -> float:
    elapsed_days = (_to_utc(as_of) - _to_utc(latest_observed_at)).total_seconds() / 86_400.0
    if elapsed_days <= 0.0:
        return 1.0
    return 0.5 ** (elapsed_days / _RETENTION_HALF_LIFE_DAYS)


@dataclass(frozen=True)
class MasteryEstimatorPolicy:
    """Lightweight FSRS-compatible placeholder over evidence history."""

    estimator_version: str = "exponential-retention-v1"
    model_attribution: str = (
        "Recency-weighted evidence history with exponential retention decay (30-day half-life)"
    )

    def estimate(
        self,
        records: list[EvidenceRecord],
        *,
        as_of: datetime | None = None,
    ) -> tuple[float, float]:
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
        if as_of is not None and all(record.observed_at is not None for record in records):
            latest_observed_at = max(record.observed_at for record in records)
            mastery *= _retention_decay_factor(latest_observed_at=latest_observed_at, as_of=as_of)
        volume = min(1.0, 0.35 + len(records) * 0.12)
        confidence = volume * (0.5 + 0.5 * mastery)
        return round(mastery, 4), round(confidence, 4)
