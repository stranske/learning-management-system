"""Load, seed, and advance per-item FSRS memory state."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from lms.auth.models import utc_now
from lms.scheduling import fsrs_engine
from lms.scheduling.models import SUBJECT_KNOWLEDGE_NODE, ReviewCardState


def get_card_state(
    session: Session,
    *,
    learner_id: str,
    subject_id: str,
    subject_type: str = SUBJECT_KNOWLEDGE_NODE,
) -> ReviewCardState | None:
    """Return the stored memory state for one learner/subject pair."""
    return session.scalars(
        select(ReviewCardState).where(
            ReviewCardState.learner_id == learner_id,
            ReviewCardState.subject_type == subject_type,
            ReviewCardState.subject_id == subject_id,
        )
    ).first()


def get_or_seed_card_state(
    session: Session,
    *,
    learner_id: str,
    subject_id: str,
    subject_type: str = SUBJECT_KNOWLEDGE_NODE,
    prior_successes: int = 0,
    retention_tier: str | None = None,
    now: datetime | None = None,
) -> ReviewCardState:
    """Return the memory state, creating it on first use.

    Items that accumulated history under the v1 ladder are seeded from that
    history (see :func:`fsrs_engine.seed_card_state_from_history`) rather than
    reset to zero, so the migration does not silently re-teach everything the
    learner already knows.
    """
    existing = get_card_state(
        session, learner_id=learner_id, subject_id=subject_id, subject_type=subject_type
    )
    if existing is not None:
        if retention_tier is not None and existing.retention_tier != retention_tier:
            existing.retention_tier = retention_tier
        return existing

    reference = now or utc_now()
    seeded = prior_successes > 0
    card_state = (
        fsrs_engine.seed_card_state_from_history(prior_successes=prior_successes, now=reference)
        if seeded
        else fsrs_engine.new_card_state()
    )
    state = ReviewCardState(
        learner_id=learner_id,
        subject_type=subject_type,
        subject_id=subject_id,
        retention_tier=retention_tier or fsrs_engine.DEFAULT_RETENTION_TIER,
        card_state=card_state,
        stability=card_state.get("stability"),
        difficulty=card_state.get("difficulty"),
        review_count=prior_successes if seeded else 0,
        seeded_from_legacy_ladder=seeded,
    )
    session.add(state)
    session.flush()
    return state


def advance_card_state(
    session: Session,
    *,
    state: ReviewCardState,
    rating_value: int,
    now: datetime | None = None,
) -> fsrs_engine.ScheduleOutcome:
    """Apply one rating to ``state`` in place and return the FSRS outcome."""
    reference = now or utc_now()
    outcome = fsrs_engine.review(
        card_state=state.card_state,
        rating_value=rating_value,
        tier=state.retention_tier,
        now=reference,
    )
    state.card_state = outcome.card_state
    state.stability = outcome.stability
    state.difficulty = outcome.difficulty
    state.due_at = outcome.due_at
    state.last_review_at = reference
    state.review_count = outcome.review_count
    state.lapse_count = outcome.lapse_count
    session.flush()
    return outcome


__all__ = ["advance_card_state", "get_card_state", "get_or_seed_card_state"]
