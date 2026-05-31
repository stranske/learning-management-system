"""Metacognitive calibration analytics.

Compares a learner's self-reported ``confidence_rating`` against their observed
accuracy (``correctness``/``normalized_score``) and response time, bucketed by
confidence level, to reveal over-confidence and weak areas.

All three raw inputs are already persisted on every ``EvidenceRecord``
(``evidence/models.py``); this module only reads and aggregates them.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from statistics import median
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from lms.evidence.models import EvidenceRecord

#: Confidence ratings at or above this level count as "high confidence".
DEFAULT_HIGH_CONFIDENCE_MIN = 4
#: Observed accuracy strictly below this counts as "low accuracy".
DEFAULT_LOW_ACCURACY_MAX = 0.5


def _record_accuracy(record: EvidenceRecord) -> float | None:
    """Return a 0..1 accuracy for one record, or ``None`` if unscored.

    Prefers the boolean ``correctness`` signal; falls back to the
    ``normalized_score`` (already constrained to the unit interval) when
    correctness was not captured.
    """
    if record.correctness is not None:
        return 1.0 if record.correctness else 0.0
    if record.normalized_score is not None:
        return float(record.normalized_score)
    return None


@dataclass(frozen=True)
class ConfidenceBucket:
    """Aggregated calibration stats for a single ``confidence_rating`` value."""

    confidence_rating: int
    count: int
    observed_accuracy: float
    median_response_time_seconds: float | None
    overconfident: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "confidence_rating": self.confidence_rating,
            "count": self.count,
            "observed_accuracy": self.observed_accuracy,
            "median_response_time_seconds": self.median_response_time_seconds,
            "overconfident": self.overconfident,
        }


@dataclass(frozen=True)
class CalibrationReport:
    """Per-learner calibration summary across confidence buckets."""

    learner_id: str
    knowledge_node_id: str | None
    sample_size: int
    buckets: list[ConfidenceBucket]
    overconfident: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "learner_id": self.learner_id,
            "knowledge_node_id": self.knowledge_node_id,
            "sample_size": self.sample_size,
            "overconfident": self.overconfident,
            "buckets": [bucket.as_dict() for bucket in self.buckets],
        }


def calibration_for_learner(
    session: Session,
    learner_id: str,
    *,
    knowledge_node_id: str | None = None,
    high_confidence_min: int = DEFAULT_HIGH_CONFIDENCE_MIN,
    low_accuracy_max: float = DEFAULT_LOW_ACCURACY_MAX,
) -> CalibrationReport:
    """Compute confidence-vs-accuracy calibration for one learner.

    Buckets every scored, confidence-rated evidence record by its
    ``confidence_rating`` and, per bucket, reports observed accuracy (mean of
    the per-record accuracy) and median response time. A bucket is flagged
    ``overconfident`` when the learner reported high confidence
    (``>= high_confidence_min``) yet observed accuracy stayed below
    ``low_accuracy_max``. The learner is ``overconfident`` if any bucket is.

    Records without a ``confidence_rating`` or without any accuracy signal are
    ignored; they cannot inform calibration.
    """
    query = select(EvidenceRecord).where(EvidenceRecord.learner_id == learner_id)
    if knowledge_node_id is not None:
        query = query.where(EvidenceRecord.knowledge_node_id == knowledge_node_id)
    records = list(session.scalars(query.order_by(EvidenceRecord.observed_at)))

    accuracies: dict[int, list[float]] = defaultdict(list)
    response_times: dict[int, list[int]] = defaultdict(list)
    sample_size = 0
    for record in records:
        if record.confidence_rating is None:
            continue
        accuracy = _record_accuracy(record)
        if accuracy is None:
            continue
        rating = record.confidence_rating
        accuracies[rating].append(accuracy)
        if record.response_time_seconds is not None:
            response_times[rating].append(record.response_time_seconds)
        sample_size += 1

    buckets: list[ConfidenceBucket] = []
    for rating in sorted(accuracies):
        bucket_accuracies = accuracies[rating]
        observed_accuracy = sum(bucket_accuracies) / len(bucket_accuracies)
        times = response_times.get(rating, [])
        median_time = float(median(times)) if times else None
        overconfident = rating >= high_confidence_min and observed_accuracy < low_accuracy_max
        buckets.append(
            ConfidenceBucket(
                confidence_rating=rating,
                count=len(bucket_accuracies),
                observed_accuracy=observed_accuracy,
                median_response_time_seconds=median_time,
                overconfident=overconfident,
            )
        )

    return CalibrationReport(
        learner_id=learner_id,
        knowledge_node_id=knowledge_node_id,
        sample_size=sample_size,
        buckets=buckets,
        overconfident=any(bucket.overconfident for bucket in buckets),
    )
