"""Derive review capacity and sustainable intake from the owner's budget.

The owner set a rough "ten minutes a day" target but asked that it be
configurable — and, more usefully, that the app *show what that budget can
actually carry* rather than hard-coding an intake ceiling. A number you can
see is a tradeoff you can make; a number buried in a constant becomes a
backlog you discover later.

The model, stated plainly so the numbers can be argued with:

* An item with effective interval ``I`` generates ``1/I`` reviews per day.
  ``I`` is measured from the FSRS engine as *lifetime days / reviews* over a
  simulated on-time streak — NOT the tier ceiling. A warm item averages ~82
  days, not its 120-day ceiling, because it spends its early life at 2, 11
  and 46 days before maturing. Using the ceiling overstates capacity by
  roughly half.
* A daily review cap ``C`` therefore supports a steady-state collection of
  about ``C x I`` items.
* Sustainable intake is bounded by TWO things, and the tighter one wins:
  the rate that fills remaining capacity over a year, and the learning load
  new items impose while bedding in (a new item needs ~2-4 reviews in its
  first month, so a sustained intake carries a permanent rolling cost). We
  allow learning to consume at most half the daily budget.

These figures assume reviews happen roughly ON TIME and mostly SUCCEED —
the intervals come from a clean success streak. Lapses reset an item toward
short intervals, so a collection with frequent failures costs more than this
predicts. Treat the numbers as an optimistic ceiling and a way to compare
budgets, not a promise.

Every figure here is an estimate shown to the owner, never a hard gate. The
hard limits live elsewhere (the daily queue cap and the draft cap).
"""

from __future__ import annotations

from dataclasses import dataclass

from lms.scheduling.fsrs_engine import COLD, HOT, RETENTION_TIERS, WARM

DEFAULT_DAILY_MINUTES: int = 10
DEFAULT_DAILY_ITEM_CAP: int = 25

# Rough seconds per item by type, from timing the real IPO items: an anchor
# is a number recalled against a band; an idea is a short written answer.
SECONDS_PER_ANCHOR: int = 20
SECONDS_PER_IDEA: int = 45

# Effective interval per tier: lifetime days divided by reviews, measured
# from the FSRS engine over an on-time success streak (see
# tests/maintenance/test_budget.py, which re-derives these and fails if the
# tier policies drift away from them).
EFFECTIVE_INTERVAL_DAYS: dict[str, float] = {HOT: 15.5, WARM: 82.4, COLD: 254.1}

# Reviews a brand-new item needs in its first month, per tier. This is the
# rolling cost a sustained intake imposes on top of the mature collection.
FIRST_MONTH_REVIEWS: dict[str, float] = {HOT: 4.0, WARM: 3.0, COLD: 2.0}

# At most half the daily budget may go on bedding in new items; the rest has
# to stay available for the collection you already have.
MAX_LEARNING_SHARE: float = 0.5

# Horizon over which remaining capacity may be filled.
FILL_HORIZON_WEEKS: int = 52


@dataclass(frozen=True)
class BudgetSettings:
    """What the owner has chosen to spend."""

    daily_minutes: int = DEFAULT_DAILY_MINUTES
    daily_item_cap: int = DEFAULT_DAILY_ITEM_CAP

    def __post_init__(self) -> None:
        if self.daily_minutes < 1:
            raise ValueError("daily_minutes must be at least 1")
        if self.daily_item_cap < 1:
            raise ValueError("daily_item_cap must be at least 1")


@dataclass(frozen=True)
class CapacityEstimate:
    """What that budget can carry, and how much of it is spoken for."""

    settings: BudgetSettings
    items_per_day: int
    steady_state_capacity: int
    active_items: int
    utilisation: float
    sustainable_new_items_per_week: int
    limited_by: str  # "minutes" | "item cap"

    @property
    def at_capacity(self) -> bool:
        return self.utilisation >= 1.0


def items_affordable_per_day(
    settings: BudgetSettings, *, anchor_share: float = 0.5
) -> tuple[int, str]:
    """How many items a day the budget buys, and which limit binds.

    ``anchor_share`` is the fraction of reviews that are quick numeric
    anchors rather than written ideas; it moves the seconds-per-item blend.
    """
    share = min(max(anchor_share, 0.0), 1.0)
    seconds_each = SECONDS_PER_ANCHOR * share + SECONDS_PER_IDEA * (1.0 - share)
    by_minutes = int((settings.daily_minutes * 60) // seconds_each)
    if by_minutes <= settings.daily_item_cap:
        return max(1, by_minutes), "minutes"
    return settings.daily_item_cap, "item cap"


def _weighted(values: dict[str, float], tier_counts: dict[str, int] | None) -> float:
    """Weight per-tier constants by how many items actually use each tier."""
    counts = {tier: (tier_counts or {}).get(tier, 0) for tier in RETENTION_TIERS}
    total = sum(counts.values())
    if total == 0:
        return values[WARM]
    return sum(values[tier] * n for tier, n in counts.items()) / total


def mean_interval_days(tier_counts: dict[str, int] | None = None) -> float:
    """Effective mean interval across the tiers actually in use."""
    return _weighted(EFFECTIVE_INTERVAL_DAYS, tier_counts)


def mean_first_month_reviews(tier_counts: dict[str, int] | None = None) -> float:
    """Reviews a new item needs in its first month, blended across tiers."""
    return _weighted(FIRST_MONTH_REVIEWS, tier_counts)


def estimate_capacity(
    settings: BudgetSettings,
    *,
    active_items: int,
    tier_counts: dict[str, int] | None = None,
    anchor_share: float = 0.5,
) -> CapacityEstimate:
    """Estimate collection capacity and a sustainable intake rate."""
    per_day, limited_by = items_affordable_per_day(settings, anchor_share=anchor_share)
    interval = mean_interval_days(tier_counts)
    capacity = max(1, int(per_day * interval))
    utilisation = active_items / capacity if capacity else 1.0

    # Bound 1: fill whatever capacity is left, spread over a year.
    headroom_items = max(0, capacity - active_items)
    by_capacity = headroom_items / FILL_HORIZON_WEEKS

    # Bound 2: a sustained intake of n items/week carries a rolling learning
    # load of n * (first-month reviews) / 4 weeks reviews per week.
    first_month = mean_first_month_reviews(tier_counts)
    weekly_learning_budget = per_day * 7 * MAX_LEARNING_SHARE
    by_learning = (weekly_learning_budget / first_month) * 4 if first_month else 0.0

    intake = int(min(by_capacity, by_learning))

    return CapacityEstimate(
        settings=settings,
        items_per_day=per_day,
        steady_state_capacity=capacity,
        active_items=active_items,
        utilisation=round(utilisation, 3),
        sustainable_new_items_per_week=max(0, intake),
        limited_by=limited_by,
    )


def describe(estimate: CapacityEstimate) -> str:
    """One plain sentence a person can act on."""
    settings = estimate.settings
    if estimate.at_capacity:
        return (
            f"{settings.daily_minutes} min/day covers about {estimate.items_per_day} reviews, "
            f"which supports roughly {estimate.steady_state_capacity} items. You have "
            f"{estimate.active_items} — at or over capacity, so adding more will crowd "
            "something out."
        )
    return (
        f"{settings.daily_minutes} min/day covers about {estimate.items_per_day} reviews "
        f"(limited by your {estimate.limited_by}), supporting roughly "
        f"{estimate.steady_state_capacity} items. You have {estimate.active_items}. "
        f"Sustainable intake at this budget: about "
        f"{estimate.sustainable_new_items_per_week} new item(s) a week. "
        "Assumes reviews land on time and mostly succeed; frequent lapses cost more."
    )


__all__ = [
    "DEFAULT_DAILY_ITEM_CAP",
    "DEFAULT_DAILY_MINUTES",
    "BudgetSettings",
    "CapacityEstimate",
    "describe",
    "estimate_capacity",
    "items_affordable_per_day",
    "mean_first_month_reviews",
    "mean_interval_days",
]
