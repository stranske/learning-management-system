"""FSRS-6 memory model behind the scheduler's existing rating seam.

The v1 scheduler used a fixed ``1, 3, 7, 14, 28`` day ladder. That ladder
cannot express the two things the maintenance strand needs:

* **Per-item retention targets.** "Keep this within working memory" and
  "keep this merely accessible over years" are different retention goals,
  not different positions on one ramp.
* **Intervals beyond 28 days.** A long-run base rate that stays useful for
  five years should not be re-asked thirteen times a year forever.

FSRS-6 (via the official ``fsrs`` package) models per-item *stability* and
*difficulty* and solves for the interval that lands on a target recall
probability. ``desired_retention`` is therefore the single dial that
expresses the owner's stated goal, and the retention tiers below turn it
into a small, choosable vocabulary.

The rating seam is unchanged: :mod:`lms.scheduling.fsrs_adapter` already
maps an ``EvidenceRecord`` onto an again/hard/good/easy rating, and the
service still blends that conservatively with its own signal classifier
before anything reaches this module. This module only answers "given a
rating, when is this item next due?".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Any, Final, cast

from fsrs import Card, Rating, Scheduler, State
from fsrs.card import CardDict

from lms.auth.models import utc_now

# Retention tiers. ``desired_retention`` is the probability of recall FSRS
# aims for at the moment an item comes due, so a higher target means shorter
# intervals and more reviews. ``maximum_interval`` is the hard ceiling that
# keeps a "cold" item from drifting out of reach entirely.
HOT: Final = "hot"
WARM: Final = "warm"
COLD: Final = "cold"
RETENTION_TIERS: Final[tuple[str, ...]] = (HOT, WARM, COLD)
DEFAULT_RETENTION_TIER: Final = WARM


@dataclass(frozen=True)
class TierPolicy:
    """Scheduling policy for one retention tier."""

    desired_retention: float
    maximum_interval_days: int
    description: str


TIER_POLICIES: Final[dict[str, TierPolicy]] = {
    # Facts used often enough that they should stay in working memory.
    HOT: TierPolicy(
        desired_retention=0.93,
        maximum_interval_days=21,
        description="Kept within working memory; checked at least every three weeks.",
    ),
    # The default: solid recall without a daily drumbeat.
    WARM: TierPolicy(
        desired_retention=0.90,
        maximum_interval_days=120,
        description="Solid recall on demand; the standard maintenance target.",
    ),
    # Low-frequency material where "I know where this lives" is the real goal.
    COLD: TierPolicy(
        desired_retention=0.85,
        maximum_interval_days=365,
        description="Kept merely accessible; recalled in gist, not verbatim.",
    ),
}

# Sub-day learning steps are Anki's cramming behavior: a new card comes back
# in one minute, then ten. This app is a once-a-day maintenance loop over
# work facts, so items graduate straight to day-scale intervals instead.
_LEARNING_STEPS: Final[tuple[timedelta, ...]] = ()
_RELEARNING_STEPS: Final[tuple[timedelta, ...]] = ()

# Legacy ladder, retained ONLY to seed FSRS state for items that accumulated
# review history under the v1 scheduler. Not used for new scheduling.
_LEGACY_LADDER_DAYS: Final[tuple[int, ...]] = (1, 3, 7, 14, 28)

RATING_BY_VALUE: Final[dict[int, Rating]] = {
    1: Rating.Again,
    2: Rating.Hard,
    3: Rating.Good,
    4: Rating.Easy,
}


def tier_policy(tier: str | None) -> TierPolicy:
    """Return the policy for ``tier``, falling back to the default tier."""
    return TIER_POLICIES.get(tier or DEFAULT_RETENTION_TIER, TIER_POLICIES[DEFAULT_RETENTION_TIER])


@lru_cache(maxsize=len(RETENTION_TIERS) + 1)
def scheduler_for_tier(tier: str) -> Scheduler:
    """Return a cached FSRS scheduler configured for one retention tier."""
    policy = tier_policy(tier)
    return Scheduler(
        desired_retention=policy.desired_retention,
        learning_steps=_LEARNING_STEPS,
        relearning_steps=_RELEARNING_STEPS,
        maximum_interval=policy.maximum_interval_days,
        # Fuzzing spreads due dates to avoid review pile-ups. It also makes
        # scheduling non-deterministic, which would break the golden-decision
        # baselines, so it stays off and the daily cap handles smoothing.
        enable_fuzzing=False,
    )


@dataclass(frozen=True)
class ScheduleOutcome:
    """The result of applying one rating to an item's memory state."""

    due_at: datetime
    interval_days: float
    card_state: dict[str, Any]
    stability: float | None
    difficulty: float | None
    review_count: int
    lapse_count: int


def new_card_state() -> dict[str, Any]:
    """Return the serialized state of a never-reviewed item."""
    return dict(Card().to_dict())


def seed_card_state_from_history(
    *,
    prior_successes: int,
    last_review_at: datetime | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Approximate FSRS state for an item that has v1 ladder history.

    Items reviewed under the fixed ladder have no stability/difficulty on
    record. Rather than resetting that history to zero, we seed a card whose
    stability equals the ladder interval the learner had already reached, so
    the first FSRS review continues from roughly where the ladder left off.
    """
    reference = now or utc_now()
    steps = max(0, prior_successes)
    index = min(steps, len(_LEGACY_LADDER_DAYS) - 1)
    stability = float(_LEGACY_LADDER_DAYS[index])
    if steps == 0:
        return new_card_state()
    card = Card(
        state=State.Review,
        stability=stability,
        # FSRS difficulty runs 1..10; 5 is the neutral midpoint and is the
        # honest choice for history that never measured difficulty.
        difficulty=5.0,
        due=reference + timedelta(days=stability),
        last_review=last_review_at or reference,
    )
    return dict(card.to_dict())


def review(
    *,
    card_state: dict[str, Any] | None,
    rating_value: int,
    tier: str | None = None,
    now: datetime | None = None,
    review_duration_ms: int | None = None,
) -> ScheduleOutcome:
    """Apply one rating and return the next due date plus the new state.

    ``rating_value`` is the 1-4 value produced by
    :func:`lms.scheduling.fsrs_adapter.evidence_to_fsrs_rating` (after the
    service's conservative blending), matching FSRS's Again/Hard/Good/Easy.
    """
    if rating_value not in RATING_BY_VALUE:
        raise ValueError(
            f"rating_value must be one of {sorted(RATING_BY_VALUE)}; got {rating_value!r}"
        )
    reference = now or utc_now()
    scheduler = scheduler_for_tier(tier or DEFAULT_RETENTION_TIER)
    card = Card.from_dict(cast("CardDict", dict(card_state))) if card_state else Card()
    previous_lapses = _lapse_count(card_state)
    previous_reviews = _review_count(card_state)

    updated, _log = scheduler.review_card(
        card,
        RATING_BY_VALUE[rating_value],
        review_datetime=reference,
        review_duration=review_duration_ms,
    )
    due_at = updated.due or reference
    state = dict(updated.to_dict())
    lapses = previous_lapses + (1 if rating_value == 1 else 0)
    state["_lapse_count"] = lapses
    state["_review_count"] = previous_reviews + 1
    return ScheduleOutcome(
        due_at=due_at,
        interval_days=max(0.0, (due_at - reference).total_seconds() / 86400.0),
        card_state=state,
        stability=updated.stability,
        difficulty=updated.difficulty,
        review_count=previous_reviews + 1,
        lapse_count=lapses,
    )


def _lapse_count(card_state: dict[str, Any] | None) -> int:
    return int((card_state or {}).get("_lapse_count", 0))


def _review_count(card_state: dict[str, Any] | None) -> int:
    return int((card_state or {}).get("_review_count", 0))


__all__ = [
    "COLD",
    "DEFAULT_RETENTION_TIER",
    "HOT",
    "RETENTION_TIERS",
    "TIER_POLICIES",
    "WARM",
    "ScheduleOutcome",
    "TierPolicy",
    "new_card_state",
    "review",
    "scheduler_for_tier",
    "seed_card_state_from_history",
    "tier_policy",
]
