"""Gate for the FSRS-6 memory model that replaced the fixed interval ladder.

The v1 scheduler could not express the two properties the maintenance strand
depends on, so these tests pin them directly:

* retention tiers produce genuinely different scheduling from the same
  rating stream (the "keep in working memory" vs "keep merely accessible"
  distinction), and
* intervals are no longer capped at the old 28-day ladder ceiling.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from lms.scheduling import fsrs_engine


def _good_streak(tier: str, rounds: int = 6) -> list[float]:
    """Interval (days) after each of ``rounds`` on-time successful reviews."""
    now = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)
    state: dict[str, object] | None = None
    intervals: list[float] = []
    for _ in range(rounds):
        outcome = fsrs_engine.review(card_state=state, rating_value=3, tier=tier, now=now)
        state = outcome.card_state
        intervals.append(outcome.interval_days)
        now = outcome.due_at
    return intervals


def test_retention_tiers_produce_distinct_schedules() -> None:
    """Same ratings, three tiers, materially different review burdens."""
    hot = _good_streak(fsrs_engine.HOT)
    warm = _good_streak(fsrs_engine.WARM)
    cold = _good_streak(fsrs_engine.COLD)

    # Each tier's mature interval is strictly longer than the tier above it.
    assert hot[-1] < warm[-1] < cold[-1]
    # And the difference is meaningful, not a rounding artifact.
    assert cold[-1] >= 3 * hot[-1]


@pytest.mark.parametrize("tier", fsrs_engine.RETENTION_TIERS)
def test_intervals_grow_then_respect_the_tier_ceiling(tier: str) -> None:
    """Successful reviews extend the interval up to (never past) the tier cap."""
    intervals = _good_streak(tier)
    cap = fsrs_engine.tier_policy(tier).maximum_interval_days

    assert intervals[1] > intervals[0], "an on-time success must extend the interval"
    assert all(value <= cap + 1e-6 for value in intervals), f"{intervals} exceeds cap {cap}"
    assert max(intervals) == pytest.approx(cap, rel=0.01), "the tier ceiling should be reached"


def test_ladder_ceiling_is_gone_for_long_horizon_items() -> None:
    """The cold tier schedules far past the old 28-day ladder maximum.

    This is the property the maintenance strand needs for multi-year material:
    a long-run base rate should not be re-asked thirteen times a year forever.
    """
    intervals = _good_streak(fsrs_engine.COLD)
    assert max(intervals) > 28, f"cold items must schedule beyond the old ladder cap: {intervals}"


def test_failure_shortens_and_counts_a_lapse() -> None:
    """An 'again' rating brings the item back promptly and records the lapse."""
    now = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)
    mature = fsrs_engine.review(card_state=None, rating_value=3, tier=fsrs_engine.WARM, now=now)
    lapsed = fsrs_engine.review(
        card_state=mature.card_state,
        rating_value=1,
        tier=fsrs_engine.WARM,
        now=mature.due_at,
    )

    assert lapsed.interval_days < mature.interval_days
    assert lapsed.lapse_count == 1
    assert lapsed.review_count == 2


def test_supported_answers_are_not_promoted_past_hard() -> None:
    """A 'hard' rating schedules sooner than a 'good' one on the same card.

    Guards the conservative-blending contract: hint-supported or low-confidence
    correct answers must not earn a full-strength interval (issue #194).
    """
    now = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)
    hard = fsrs_engine.review(card_state=None, rating_value=2, tier=fsrs_engine.WARM, now=now)
    good = fsrs_engine.review(card_state=None, rating_value=3, tier=fsrs_engine.WARM, now=now)

    assert hard.interval_days <= good.interval_days


def test_legacy_ladder_history_is_seeded_not_reset() -> None:
    """Items with v1 ramp history keep their strength instead of restarting."""
    now = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)
    fresh = fsrs_engine.new_card_state()
    seeded = fsrs_engine.seed_card_state_from_history(prior_successes=3, now=now)

    assert fresh.get("stability") in (None, 0)
    assert seeded["stability"] == pytest.approx(14.0), "ladder step 3 was the 14-day interval"

    # A seeded item schedules further out than a brand-new one.
    from_fresh = fsrs_engine.review(card_state=fresh, rating_value=3, now=now)
    from_seeded = fsrs_engine.review(card_state=seeded, rating_value=3, now=now)
    assert from_seeded.interval_days > from_fresh.interval_days


def test_zero_history_seeds_a_brand_new_card() -> None:
    """No prior successes means no invented memory strength."""
    seeded = fsrs_engine.seed_card_state_from_history(prior_successes=0)
    fresh = fsrs_engine.new_card_state()
    # card_id/due are per-instance stamps; the memory-bearing fields are what
    # must match a never-reviewed card.
    memory_fields = ("state", "stability", "difficulty", "step")
    assert {k: seeded.get(k) for k in memory_fields} == {k: fresh.get(k) for k in memory_fields}


def test_rejects_out_of_range_rating() -> None:
    """Only FSRS's 1-4 rating vocabulary is accepted."""
    with pytest.raises(ValueError, match="rating_value"):
        fsrs_engine.review(card_state=None, rating_value=5)


def test_scheduling_is_deterministic() -> None:
    """Fuzzing is off so golden decision baselines stay reproducible."""
    now = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)
    first = fsrs_engine.review(card_state=None, rating_value=3, now=now)
    second = fsrs_engine.review(card_state=None, rating_value=3, now=now)
    assert first.due_at == second.due_at


def test_no_sub_day_learning_steps() -> None:
    """New items graduate to day-scale intervals, not Anki-style cramming."""
    now = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)
    outcome = fsrs_engine.review(card_state=None, rating_value=3, now=now)
    assert outcome.due_at - now >= timedelta(hours=20)
