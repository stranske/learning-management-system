"""Scheduler service that maps attempts and evidence into review queue items.

The v1 policy is deliberately deterministic and explainable. For the
success path the FSRS evidence adapter is consulted: its rating label and
rule_id are recorded in the decision log for the Inspect surface. When FSRS
returns ``insufficient-signal`` or an excluded rating the internal
``_classify_signal`` function is used as a fallback so edge cases (e.g.
no explicit correctness flag but a partial score) are handled conservatively.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from lms.auth.models import utc_now
from lms.evidence.models import Attempt, EvidenceRecord
from lms.scheduling.fsrs_adapter import FSRSRating, evidence_to_fsrs_rating
from lms.scheduling.models import ReviewQueueItem
from lms.scheduling.repository import create_review_queue_item

DEFAULT_DAILY_CAP = 25
DEFAULT_RESUME_DAILY_CAP = 10
DEFAULT_STALE_AFTER_DAYS = 45

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


@dataclass(frozen=True)
class SchedulerSettings:
    """Learner-level scheduling controls for the v1 queue policy."""

    daily_cap: int = DEFAULT_DAILY_CAP
    pause_until: datetime | None = None
    resume_daily_cap: int = DEFAULT_RESUME_DAILY_CAP
    stale_after_days: int = DEFAULT_STALE_AFTER_DAYS

    def __post_init__(self) -> None:
        if self.daily_cap < 1:
            raise ValueError("daily_cap must be at least 1")
        if self.resume_daily_cap < 1:
            raise ValueError("resume_daily_cap must be at least 1")
        if self.stale_after_days < 1:
            raise ValueError("stale_after_days must be at least 1")


@dataclass(frozen=True)
class ReviewQueueOverview:
    """A capped queue plus total backlog context for API responses."""

    items: list[ReviewQueueItem]
    backlog_total: int
    daily_cap: int
    backlog_note: str


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


def _pending_queue_statement(*, learner_id: str) -> Any:
    """Return the standard pending queue statement ordered by scheduler priority."""
    return (
        select(ReviewQueueItem)
        .where(
            ReviewQueueItem.learner_id == learner_id,
            ReviewQueueItem.status == "pending",
        )
        .order_by(
            ReviewQueueItem.due_at.asc(),
            ReviewQueueItem.priority.desc(),
            ReviewQueueItem.id,
        )
    )


def _append_decision_event(item: ReviewQueueItem, event: dict[str, Any]) -> None:
    """Add a deterministic event to the queue item's decision log."""
    log = dict(item.decision_log or {})
    events = list(log.get("events", []))
    events.append(event)
    log["events"] = events
    item.decision_log = log


def freeze_due_items_for_pause(
    session: Session,
    *,
    learner_id: str,
    pause_until: datetime,
    now: datetime | None = None,
) -> int:
    """Freeze pending items due within the pause window until the window ends."""
    decision_now = now or utc_now()
    if pause_until <= decision_now:
        return 0

    items = list(
        session.scalars(
            _pending_queue_statement(learner_id=learner_id).where(
                ReviewQueueItem.due_at <= pause_until,
                ReviewQueueItem.reason_code != "stale",
            )
        )
    )
    for item in items:
        original_due_at = item.due_at
        item.due_at = pause_until
        item.priority = min(item.priority, 0.6)
        _append_decision_event(
            item,
            {
                "rule": "pause-freeze",
                "at": decision_now.isoformat(),
                "original_due_at": original_due_at.isoformat(),
                "pause_until": pause_until.isoformat(),
            },
        )
    session.flush()
    return len(items)


def mark_stale_queue_items(
    session: Session,
    *,
    learner_id: str,
    stale_after_days: int = DEFAULT_STALE_AFTER_DAYS,
    now: datetime | None = None,
) -> int:
    """Mark old pending items stale instead of forcing a large overdue queue."""
    if stale_after_days < 1:
        raise ValueError("stale_after_days must be at least 1")
    decision_now = now or utc_now()
    stale_before = decision_now - timedelta(days=stale_after_days)
    items = list(
        session.scalars(
            _pending_queue_statement(learner_id=learner_id).where(
                ReviewQueueItem.due_at < stale_before,
                ReviewQueueItem.reason_code.in_(("new-learning", "due-review", "overdue")),
            )
        )
    )
    for item in items:
        original_reason_code = item.reason_code
        original_due_at = item.due_at
        item.reason_code = "stale"
        item.reason_explanation = (
            "This item is old enough to be treated as stale. Re-engage it, retire it, "
            "or adjust the learning goal instead of forcing catch-up."
        )
        item.priority = min(item.priority, 0.3)
        _append_decision_event(
            item,
            {
                "rule": "mark-stale",
                "at": decision_now.isoformat(),
                "stale_after_days": stale_after_days,
                "original_reason_code": original_reason_code,
                "original_due_at": original_due_at.isoformat(),
            },
        )
    session.flush()
    return len(items)


def apply_resume_ramp(
    session: Session,
    *,
    learner_id: str,
    daily_cap: int = DEFAULT_RESUME_DAILY_CAP,
    now: datetime | None = None,
) -> int:
    """Spread an overdue backlog over future days after a pause."""
    if daily_cap < 1:
        raise ValueError("daily_cap must be at least 1")
    decision_now = now or utc_now()
    due_items = list(
        session.scalars(
            _pending_queue_statement(learner_id=learner_id).where(
                ReviewQueueItem.due_at <= decision_now,
                ReviewQueueItem.reason_code != "stale",
            )
        )
    )
    changed = 0
    for index, item in enumerate(due_items):
        day_offset = index // daily_cap
        target_due_at = decision_now + timedelta(days=day_offset)
        if item.due_at != target_due_at:
            original_due_at = item.due_at
            item.due_at = target_due_at
            _append_decision_event(
                item,
                {
                    "rule": "resume-ramp",
                    "at": decision_now.isoformat(),
                    "daily_cap": daily_cap,
                    "original_due_at": original_due_at.isoformat(),
                    "new_due_at": target_due_at.isoformat(),
                },
            )
            changed += 1
    session.flush()
    return changed


def get_review_queue_overview(
    session: Session,
    *,
    learner_id: str,
    settings: SchedulerSettings | None = None,
    now: datetime | None = None,
) -> ReviewQueueOverview:
    """Return a capped pending queue view without mutating persisted queue state."""
    scheduler_settings = settings or SchedulerSettings()

    backlog_total = int(
        session.scalar(
            select(func.count())
            .select_from(ReviewQueueItem)
            .where(
                ReviewQueueItem.learner_id == learner_id,
                ReviewQueueItem.status == "pending",
            )
        )
        or 0
    )
    items = list(
        session.scalars(
            _pending_queue_statement(learner_id=learner_id).limit(scheduler_settings.daily_cap)
        )
    )
    backlog_note = (
        f"{backlog_total} pending item(s); showing up to "
        f"{scheduler_settings.daily_cap} today. The total is informational, not an "
        "obligation score."
    )
    return ReviewQueueOverview(
        items=items,
        backlog_total=backlog_total,
        daily_cap=scheduler_settings.daily_cap,
        backlog_note=backlog_note,
    )


def _success_interval_days(prior_successes: int) -> int:
    """Pick a v1 spaced-repetition interval from a fixed ramp."""
    if prior_successes < 0:
        prior_successes = 0
    if prior_successes >= len(SUCCESS_INTERVALS_DAYS):
        return SUCCESS_INTERVALS_DAYS[-1]
    return SUCCESS_INTERVALS_DAYS[prior_successes]


_SIGNAL_ORDER: dict[str, int] = {"fail": 0, "low-confidence-success": 1, "success": 2}


def _fsrs_to_signal(rating: FSRSRating) -> str | None:
    """Map a clear FSRS rating to an internal signal string.

    Returns None when FSRS cannot give a clear signal (insufficient-signal or
    excluded), indicating the caller should fall back to ``_classify_signal``.
    """
    if not rating.scheduling_included or rating.rule_id == "insufficient-signal":
        return None
    if rating.value == 1:
        return "fail"
    if rating.value == 2:
        return "low-confidence-success"
    return "success"


def _conservative_signal(a: str, b: str) -> str:
    """Return the more conservative (lower-confidence) of two signal strings."""
    return a if _SIGNAL_ORDER[a] <= _SIGNAL_ORDER[b] else b


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

    fsrs_rating = evidence_to_fsrs_rating(evidence_record)
    internal_signal = _classify_signal(
        correctness=correctness,
        normalized_score=normalized_score,
        confidence_rating=confidence_rating,
        support_level=support_level,
    )
    fsrs_signal = _fsrs_to_signal(fsrs_rating)
    # When FSRS gives a clear verdict, blend conservatively with the internal
    # classifier so low-confidence or supported responses are never upgraded.
    signal = (
        _conservative_signal(fsrs_signal, internal_signal)
        if fsrs_signal is not None
        else internal_signal
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
        "fsrs_rating": {
            "label": fsrs_rating.label,
            "value": fsrs_rating.value,
            "rule_id": fsrs_rating.rule_id,
            "scheduling_included": fsrs_rating.scheduling_included,
        },
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
