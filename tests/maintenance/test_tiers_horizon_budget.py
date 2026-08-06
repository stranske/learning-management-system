"""Gates for per-item tier editing, horizon retirement, and the review budget."""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import lms.audit.models  # noqa: F401
import lms.cases.models  # noqa: F401
import lms.evidence.models  # noqa: F401
import lms.feedback.models  # noqa: F401
import lms.graphs.models  # noqa: F401
import lms.learners.models  # noqa: F401
import lms.llm.models  # noqa: F401
import lms.llm.proposals  # noqa: F401
import lms.maintenance.models  # noqa: F401
import lms.prompts.models  # noqa: F401
import lms.scheduling.models  # noqa: F401
import lms.sources.models  # noqa: F401
from lms.auth.repository import get_or_create_local_dev_user
from lms.db.base import Base
from lms.db.session import get_session
from lms.learners.models import Learner
from lms.learners.repository import create_learner_for_user
from lms.main import create_app
from lms.maintenance.budget import (
    EFFECTIVE_INTERVAL_DAYS,
    BudgetSettings,
    describe,
    estimate_capacity,
    items_affordable_per_day,
    mean_interval_days,
)
from lms.maintenance.models import MaintenanceItem
from lms.maintenance.seeds import ipo_surge_2026
from lms.maintenance.service import (
    retire_by_subject,
    retire_expired_items,
    set_item_tier,
    submit_review,
    tier_counts,
)
from lms.scheduling import fsrs_engine
from lms.scheduling.card_state import get_card_state
from lms.scheduling.models import SUBJECT_MAINTENANCE_ITEM

MAINTENANCE = "/app/learner/maintenance"
ITEM = f"{MAINTENANCE}/item"


@pytest.fixture
def env() -> Generator[tuple[TestClient, sessionmaker[Session], str], None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    def override() -> Generator[Session, None, None]:
        s = factory()
        try:
            yield s
        finally:
            s.close()

    with factory() as session:
        user = get_or_create_local_dev_user(session)
        learner = create_learner_for_user(session, user_id=user.id, display_name="Owner")
        for spec in ipo_surge_2026.all_items():
            session.add(MaintenanceItem(learner_id=learner.id, status="active", **spec))
        session.commit()
        learner_id = learner.id

    app = create_app(enable_local_identity_routes=True)
    app.dependency_overrides[get_session] = override
    client = TestClient(app, follow_redirects=False)
    try:
        yield client, factory, learner_id
    finally:
        client.close()
        app.dependency_overrides.clear()


def _any_item(factory: sessionmaker[Session]) -> MaintenanceItem:
    with factory() as session:
        return session.scalars(
            select(MaintenanceItem).where(MaintenanceItem.status == "active")
        ).first()


# --- per-item tier editing ------------------------------------------------


def test_changing_tier_updates_the_live_card_too(
    env: tuple[TestClient, sessionmaker[Session], str],
) -> None:
    """The tier lives on the item but scheduling reads the card — keep both in step."""
    _client, factory, learner_id = env
    item = _any_item(factory)

    with factory() as session:
        fresh = session.get(MaintenanceItem, item.id)
        submit_review(session, item=fresh, answer="about 100")
        session.commit()
        before = get_card_state(
            session,
            learner_id=learner_id,
            subject_id=item.id,
            subject_type=SUBJECT_MAINTENANCE_ITEM,
        )
        assert before is not None
        original = before.retention_tier

        set_item_tier(session, item=fresh, retention_tier="hot")
        session.commit()

        after = get_card_state(
            session,
            learner_id=learner_id,
            subject_id=item.id,
            subject_type=SUBJECT_MAINTENANCE_ITEM,
        )
    assert original != "hot"
    assert after is not None
    assert after.retention_tier == "hot", "card must follow the item's tier"


def test_item_settings_page_saves_tier_precision_and_horizon(
    env: tuple[TestClient, sessionmaker[Session], str],
) -> None:
    client, factory, _learner = env
    item = _any_item(factory)

    page = client.get(f"{ITEM}?item_id={item.id}")
    assert page.status_code == 200
    assert "Retention tier" in page.text

    saved = client.post(
        ITEM,
        data={
            "item_id": item.id,
            "retention_tier": "hot",
            "precision_mode": "exact",
            "relevant_until": "2027-01-31",
        },
    )

    assert saved.status_code == 303
    with factory() as session:
        refreshed = session.get(MaintenanceItem, item.id)
    assert refreshed.retention_tier == "hot"
    assert refreshed.precision_mode == "exact"
    assert refreshed.relevant_until.date().isoformat() == "2027-01-31"


def test_clearing_the_horizon_removes_it(
    env: tuple[TestClient, sessionmaker[Session], str],
) -> None:
    """An empty date field means 'no horizon', not 'leave it alone'."""
    client, factory, _learner = env
    item = _any_item(factory)
    client.post(ITEM, data={"item_id": item.id, "relevant_until": "2027-01-31"})

    client.post(ITEM, data={"item_id": item.id, "relevant_until": ""})

    with factory() as session:
        assert session.get(MaintenanceItem, item.id).relevant_until is None


def test_retire_now_takes_an_item_out_of_the_loop(
    env: tuple[TestClient, sessionmaker[Session], str],
) -> None:
    client, factory, _learner = env
    item = _any_item(factory)

    client.post(f"{ITEM}/retire", data={"item_id": item.id})

    with factory() as session:
        assert session.get(MaintenanceItem, item.id).status == "retired"
    assert item.title not in client.get(MAINTENANCE).text


def test_item_settings_are_learner_scoped(
    env: tuple[TestClient, sessionmaker[Session], str],
) -> None:
    client, factory, _learner = env
    with factory() as session:
        other = create_learner_for_user(
            session,
            user_id=get_or_create_local_dev_user(session).id,
            display_name="Someone else",
        )
        foreign = MaintenanceItem(
            learner_id=other.id,
            item_type="idea",
            title="Not yours",
            prompt="?",
            payload={},
            status="active",
        )
        session.add(foreign)
        session.commit()
        foreign_id = foreign.id

    assert client.get(f"{ITEM}?item_id={foreign_id}").status_code == 404
    assert client.post(ITEM, data={"item_id": foreign_id}).status_code == 404


# --- horizon retirement ---------------------------------------------------


def test_items_past_their_horizon_are_retired_not_just_hidden(
    env: tuple[TestClient, sessionmaker[Session], str],
) -> None:
    """Leaving them active made the counts lie, which corrupts capacity estimates."""
    _client, factory, learner_id = env
    with factory() as session:
        item = session.scalars(
            select(MaintenanceItem).where(MaintenanceItem.status == "active")
        ).first()
        item.relevant_until = datetime.now(UTC) - timedelta(days=1)
        session.commit()

        retired = retire_expired_items(session, learner_id=learner_id)
        session.commit()

        assert [r.id for r in retired] == [item.id]
        assert session.get(MaintenanceItem, item.id).status == "retired"


def test_items_within_their_horizon_survive_the_sweep(
    env: tuple[TestClient, sessionmaker[Session], str],
) -> None:
    _client, factory, learner_id = env
    with factory() as session:
        item = session.scalars(
            select(MaintenanceItem).where(MaintenanceItem.status == "active")
        ).first()
        item.relevant_until = datetime.now(UTC) + timedelta(days=30)
        session.commit()

        assert retire_expired_items(session, learner_id=learner_id) == []


def test_the_sweep_runs_when_the_maintenance_page_loads(
    env: tuple[TestClient, sessionmaker[Session], str],
) -> None:
    client, factory, _learner = env
    with factory() as session:
        item = session.scalars(
            select(MaintenanceItem).where(MaintenanceItem.status == "active")
        ).first()
        item.relevant_until = datetime.now(UTC) - timedelta(days=1)
        session.commit()
        item_id = item.id

    page = client.get(MAINTENANCE)

    assert "passed their relevance horizon and were retired" in page.text
    with factory() as session:
        assert session.get(MaintenanceItem, item_id).status == "retired"


def test_retiring_a_whole_subject_at_once(
    env: tuple[TestClient, sessionmaker[Session], str],
) -> None:
    """Exiting a manager should not mean retiring twenty items one by one."""
    _client, factory, learner_id = env
    with factory() as session:
        retired = retire_by_subject(
            session, learner_id=learner_id, subject_label=ipo_surge_2026.SUBJECT
        )
        session.commit()
        assert len(retired) == 6
        remaining = session.scalars(
            select(MaintenanceItem).where(MaintenanceItem.status == "active")
        ).all()
    assert remaining == []


# --- budget ---------------------------------------------------------------


def test_effective_intervals_match_the_engine() -> None:
    """The capacity model's constants must track the real FSRS tier behavior.

    If a tier policy changes, this fails rather than letting the budget
    silently advertise a capacity the scheduler will not deliver.
    """
    for tier, expected in EFFECTIVE_INTERVAL_DAYS.items():
        now = datetime(2026, 1, 1, tzinfo=UTC)
        state: dict[str, object] | None = None
        elapsed = 0.0
        for _ in range(8):
            outcome = fsrs_engine.review(card_state=state, rating_value=3, tier=tier, now=now)
            state = outcome.card_state
            elapsed += outcome.interval_days
            now = outcome.due_at
        measured = elapsed / 8
        assert measured == pytest.approx(expected, rel=0.05), f"{tier}: {measured:.1f}"


def test_capacity_uses_effective_intervals_not_tier_ceilings() -> None:
    """Using the ceiling would overstate capacity by roughly half."""
    warm_effective = mean_interval_days({"warm": 10})
    warm_ceiling = fsrs_engine.tier_policy("warm").maximum_interval_days

    assert warm_effective < warm_ceiling
    assert warm_effective == pytest.approx(82.4, rel=0.01)


def test_bigger_budget_buys_more_capacity_and_intake() -> None:
    small = estimate_capacity(BudgetSettings(daily_minutes=5), active_items=0)
    large = estimate_capacity(BudgetSettings(daily_minutes=20), active_items=0)

    assert large.items_per_day > small.items_per_day
    assert large.steady_state_capacity > small.steady_state_capacity
    assert large.sustainable_new_items_per_week > small.sustainable_new_items_per_week


def test_intake_falls_as_the_collection_fills_and_hits_zero_at_capacity() -> None:
    settings = BudgetSettings(daily_minutes=10)
    empty = estimate_capacity(settings, active_items=0)
    full = estimate_capacity(settings, active_items=empty.steady_state_capacity)

    assert empty.sustainable_new_items_per_week > 0
    assert full.sustainable_new_items_per_week == 0
    assert full.at_capacity
    assert "crowd" in describe(full)


def test_whichever_limit_binds_is_reported() -> None:
    """The owner should know whether minutes or the item cap is the constraint."""
    by_minutes = items_affordable_per_day(BudgetSettings(daily_minutes=2, daily_item_cap=100))
    by_cap = items_affordable_per_day(BudgetSettings(daily_minutes=120, daily_item_cap=5))

    assert by_minutes[1] == "minutes"
    assert by_cap == (5, "item cap")


def test_budget_settings_reject_nonsense() -> None:
    with pytest.raises(ValueError, match="daily_minutes"):
        BudgetSettings(daily_minutes=0)
    with pytest.raises(ValueError, match="daily_item_cap"):
        BudgetSettings(daily_item_cap=0)


def test_budget_panel_renders_and_updates(
    env: tuple[TestClient, sessionmaker[Session], str],
) -> None:
    client, factory, learner_id = env

    page = client.get(MAINTENANCE)
    assert "Your budget" in page.text
    assert "min/day covers about" in page.text
    # The estimate is labelled as an estimate, not a promise.
    assert "Assumes reviews land on time" in page.text

    client.post(f"{MAINTENANCE}/budget", data={"daily_minutes": "25", "daily_item_cap": "40"})

    with factory() as session:
        learner = session.get(Learner, learner_id)
    assert learner.daily_minutes_target == 25
    assert learner.daily_item_cap == 40
    assert "25 min/day" in client.get(MAINTENANCE).text


def test_budget_input_is_clamped_not_trusted(
    env: tuple[TestClient, sessionmaker[Session], str],
) -> None:
    client, factory, learner_id = env

    client.post(f"{MAINTENANCE}/budget", data={"daily_minutes": "99999", "daily_item_cap": "-4"})

    with factory() as session:
        learner = session.get(Learner, learner_id)
    assert learner.daily_minutes_target == 240
    assert learner.daily_item_cap == 1


def test_tier_counts_feed_the_capacity_estimate(
    env: tuple[TestClient, sessionmaker[Session], str],
) -> None:
    """A cold-heavy collection is cheaper to maintain than a hot-heavy one."""
    _client, factory, learner_id = env
    with factory() as session:
        counts = tier_counts(session, learner_id=learner_id)
    assert sum(counts.values()) == 6

    hot_heavy = estimate_capacity(BudgetSettings(), active_items=100, tier_counts={"hot": 100})
    cold_heavy = estimate_capacity(BudgetSettings(), active_items=100, tier_counts={"cold": 100})

    assert cold_heavy.steady_state_capacity > hot_heavy.steady_state_capacity


def test_retire_is_visually_separated_from_save(
    env: tuple[TestClient, sessionmaker[Session], str],
) -> None:
    """A destructive action must not render identically to Save beside it.

    Found by driving the page: "Save" and "Retire this item now" were both
    full-width primary buttons, one click apart.
    """
    client, factory, _learner = env
    item = _any_item(factory)

    page = client.get(f"{ITEM}?item_id={item.id}").text

    assert "danger-zone" in page
    assert 'class="b-danger"' in page
    assert "will not come back" in page, "the consequence must be stated"
