"""Scheduler service that maps attempts and evidence into review queue items.

The v1 policy is deliberately deterministic and explainable. The dispatch
table below is the FSRS-integration extension point: when the FSRS evidence
adapter lands, ``_compute_schedule`` can delegate to it for the success-path
intervals while keeping the same decision-log shape for Inspect.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from lms.auth.models import utc_now
from lms.evidence.models import Attempt, EvidenceRecord
from lms.scheduling.models import ReviewQueueItem
from lms.scheduling.repository import create_review_queue_item

SUCCESS_INTERVALS_DAYS: tuple[int, ...] = (1, 3, 7, 14, 28)
LOW_CONFIDENCE_INTERVAL_DAYS = 1
SUCCESS_SCORE_THRESHOLD = 0.85
FAILURE_SCORE_THRESHOLD = 0.5
LOW_CONFIDENCE_RATING_CEILING = 2


@dataclass(frozen=True)
class ScheduleDecision:
    """A scheduler decision rendered into a review queue item."""

    reason_code: str
    reason_explanation: str
    due_at: datetime
    priority: float
    rule: str


def _count_prior_successful_reviews(
    session: Session, *, learner_id: str, knowledge_node_id: str
) -> int:
    """Count past completed due-review/new-learning items for this learner+node."""
    statement = (
        select(func.count())
        .select_from(ReviewQueueItem)
        .where(
            ReviewQueueItem.learner_id == learner_id,
            ReviewQueueItem.knowledge_node_id == knowledge_node_id,
            ReviewQueueItem.status == "completed",
            ReviewQueueItem.reason_code.in_(("due-review", "new-learning")),
        )
    )
    return int(session.scalar(statement) or 0)


def _success_interval_days(prior_successes: int) -> int:
    """Pick a v1 spaced-repetition interval from a fixed ramp."""
    if prior_successes < 0:
        prior_successes = 0
    if prior_successes >= len(SUCCESS_INTERVALS_DAYS):
        return SUCCESS_INTERVALS_DAYS[-1]
    return SUCCESS_INTERVALS_DAYS[prior_successes]


def _classify_signal(
    *,
    correctness: bool | None,
    normalized_score: float | None,
    confidence_rating: int | None,
    support_level: str,
) -> str:
    """Return one of: 'fail', 'low-confidence-success', 'success'."""
    if correctness is False:
        return "fail"
    if normalized_score is not None and normalized_score < FAILURE_SCORE_THRESHOLD:
        return "fail"
    if (
        confidence_rating is not None
        and confidence_rating <= LOW_CONFIDENCE_RATING_CEILING
        and (correctness is True or normalized_score is not None)
    ):
        return "low-confidence-success"
    if support_level not in ("none", ""):
        return "low-confidence-success"
    if normalized_score is not None and normalized_score < SUCCESS_SCORE_THRESHOLD:
        return "low-confidence-success"
    if correctness is True or (
        normalized_score is not None and normalized_score >= SUCCESS_SCORE_THRESHOLD
    ):
        return "success"
    return "low-confidence-success"


def _explain_success(prior_successes: int, interval_days: int) -> str:
    """Render plain-language explanation for a scheduled future review."""
    if prior_successes == 0:
        return (
            f"Correct on first review. Re-checking in {interval_days} day(s) to "
            "confirm retention while the memory is fresh."
        )
    return (
        f"{prior_successes} prior successful review(s) on this concept. "
        f"Next check scheduled in {interval_days} day(s) using the v1 spaced ramp."
    )


def _explain_low_confidence(reason: str) -> str:
    """Render plain-language explanation for a low-confidence success."""
    return (
        "Got it, but with low confidence or support "
        f"({reason}). Scheduling a short follow-up review to consolidate before "
        "stretching the interval."
    )


def _explain_failure() -> str:
    """Render plain-language explanation for a failed retrieval."""
    return (
        "Did not retrieve the target. Adding an immediate remediation item so the "
        "learner can rebuild the connection before more practice."
    )


def _decide(
    *,
    signal: str,
    now: datetime,
    prior_successes: int,
    confidence_rating: int | None,
    support_level: str,
    normalized_score: float | None,
) -> ScheduleDecision:
    """Translate a classified signal into a single scheduling decision."""
    if signal == "fail":
        return ScheduleDecision(
            reason_code="remediation",
            reason_explanation=_explain_failure(),
            due_at=now,
            priority=0.9,
            rule="failure-immediate-remediation",
        )
    if signal == "low-confidence-success":
        reasons: list[str] = []
        if confidence_rating is not None and confidence_rating <= LOW_CONFIDENCE_RATING_CEILING:
            reasons.append(f"confidence={confidence_rating}/5")
        if support_level not in ("none", ""):
            reasons.append(f"support={support_level}")
        if normalized_score is not None and normalized_score < SUCCESS_SCORE_THRESHOLD:
            reasons.append(f"normalized_score={normalized_score:.2f}")
        if not reasons:
            reasons.append("low-confidence signal")
        return ScheduleDecision(
            reason_code="due-review",
            reason_explanation=_explain_low_confidence(", ".join(reasons)),
            due_at=now + timedelta(days=LOW_CONFIDENCE_INTERVAL_DAYS),
            priority=0.7,
            rule="low-confidence-shortened-interval",
        )
    interval = _success_interval_days(prior_successes)
    return ScheduleDecision(
        reason_code="due-review",
        reason_explanation=_explain_success(prior_successes, interval),
        due_at=now + timedelta(days=interval),
        priority=0.4,
        rule=f"success-ramp-step-{prior_successes}",
    )


def schedule_from_attempt(
    session: Session,
    *,
    attempt: Attempt,
    evidence_record: EvidenceRecord | None,
    now: datetime | None = None,
) -> ReviewQueueItem:
    """Create a review queue item from an attempt and (optionally) its evidence.

    Returns a single new queue item. The decision log captures the inputs and
    the rule that fired so the Inspect surface can render the explanation.
    """
    if evidence_record is not None and evidence_record.attempt_id != attempt.id:
        raise ValueError("evidence_record does not belong to attempt")
    if evidence_record is None:
        raise ValueError("schedule_from_attempt requires an evidence_record for v1")

    decision_now = now or utc_now()
    prior_successes = _count_prior_successful_reviews(
        session,
        learner_id=attempt.learner_id,
        knowledge_node_id=evidence_record.knowledge_node_id,
    )
    correctness = evidence_record.correctness
    normalized_score = evidence_record.normalized_score
    confidence_rating = evidence_record.confidence_rating
    support_level = evidence_record.support_level or "none"
    signal = _classify_signal(
        correctness=correctness,
        normalized_score=normalized_score,
        confidence_rating=confidence_rating,
        support_level=support_level,
    )
    decision = _decide(
        signal=signal,
        now=decision_now,
        prior_successes=prior_successes,
        confidence_rating=confidence_rating,
        support_level=support_level,
        normalized_score=normalized_score,
    )
    decision_log: dict[str, Any] = {
        "rule": decision.rule,
        "signal": signal,
        "inputs": {
            "correctness": correctness,
            "normalized_score": normalized_score,
            "confidence_rating": confidence_rating,
            "support_level": support_level,
            "prior_successful_reviews": prior_successes,
            "evidence_record_id": evidence_record.id,
            "attempt_id": attempt.id,
        },
        "output": {
            "reason_code": decision.reason_code,
            "due_at": decision.due_at.isoformat(),
            "priority": decision.priority,
        },
    }
    return create_review_queue_item(
        session,
        learner_id=attempt.learner_id,
        knowledge_node_id=evidence_record.knowledge_node_id,
        reason_code=decision.reason_code,
        reason_explanation=decision.reason_explanation,
        due_at=decision.due_at,
        priority=decision.priority,
        source_attempt_id=attempt.id,
        source_evidence_record_id=evidence_record.id,
        decision_log=decision_log,
    )


def seed_new_learning_item(
    session: Session,
    *,
    learner_id: str,
    knowledge_node_id: str,
    explanation: str | None = None,
    priority: float = 0.5,
    now: datetime | None = None,
) -> ReviewQueueItem:
    """Add a ``new-learning`` queue item for a learner+node with no prior evidence."""
    decision_now = now or utc_now()
    text = (
        explanation
        or "Introducing this concept. Surfaces a first practice item before any "
        "evidence has been collected."
    )
    decision_log = {
        "rule": "seed-new-learning",
        "signal": "new-learning",
        "inputs": {
            "learner_id": learner_id,
            "knowledge_node_id": knowledge_node_id,
        },
        "output": {
            "reason_code": "new-learning",
            "due_at": decision_now.isoformat(),
            "priority": priority,
        },
    }
    return create_review_queue_item(
        session,
        learner_id=learner_id,
        knowledge_node_id=knowledge_node_id,
        reason_code="new-learning",
        reason_explanation=text,
        due_at=decision_now,
        priority=priority,
        decision_log=decision_log,
    )
