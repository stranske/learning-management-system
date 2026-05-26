"""Acceptance tests for scheduler sustainability controls (issue #24).

The three test functions in this module are the literal acceptance criteria for
issue #24 ("Add daily cap, pause mode, and stale handling"). They were
previously defined in ``tests/scheduling/test_review_queue.py``; this module
hosts them at the path the acceptance criteria name explicitly so the
PR/verifier surface can locate them by the documented file name.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from lms.auth.models import utc_now
from lms.scheduling.service import (
    SchedulerSettings,
    apply_resume_ramp,
    freeze_due_items_for_pause,
    get_review_queue_overview,
    mark_stale_queue_items,
    seed_new_learning_item,
)


def test_daily_cap_limits_returned_queue_items(db_session: Session) -> None:
    """The queue overview returns only today's capped load while reporting total backlog."""
    fixed_now = datetime(2026, 6, 1, 12, 0, 0, tzinfo=utc_now().tzinfo)
    created = [
        seed_new_learning_item(
            db_session,
            learner_id="learner-cap",
            knowledge_node_id=f"node-{index}",
            now=fixed_now + timedelta(minutes=index),
        )
        for index in range(4)
    ]
    db_session.commit()

    overview = get_review_queue_overview(
        db_session,
        learner_id="learner-cap",
        settings=SchedulerSettings(daily_cap=2),
        now=fixed_now,
    )

    assert overview.backlog_total == 4
    assert overview.daily_cap == 2
    assert [item.id for item in overview.items] == [created[0].id, created[1].id]
    assert "informational" in overview.backlog_note
    assert "obligation score" in overview.backlog_note


def test_pause_freezes_due_times_and_resume_ramps_items(db_session: Session) -> None:
    """Pause mode defers due items and resume ramp spreads the backlog."""
    fixed_now = datetime(2026, 6, 1, 12, 0, 0, tzinfo=utc_now().tzinfo)
    pause_until = fixed_now + timedelta(days=7)
    items = [
        seed_new_learning_item(
            db_session,
            learner_id="learner-pause",
            knowledge_node_id=f"node-{index}",
            now=fixed_now - timedelta(days=index + 1),
        )
        for index in range(4)
    ]

    frozen = freeze_due_items_for_pause(
        db_session,
        learner_id="learner-pause",
        pause_until=pause_until,
        now=fixed_now,
    )
    assert frozen == 4
    assert {item.due_at for item in items} == {pause_until}
    assert all(item.decision_log["events"][-1]["rule"] == "pause-freeze" for item in items)

    resume_now = pause_until + timedelta(days=1)
    changed = apply_resume_ramp(
        db_session,
        learner_id="learner-pause",
        daily_cap=2,
        now=resume_now,
    )

    assert changed == 4
    due_dates = [item.due_at for item in items]
    assert due_dates.count(resume_now) == 2
    assert due_dates.count(resume_now + timedelta(days=1)) == 2
    assert all(item.decision_log["events"][-1]["rule"] == "resume-ramp" for item in items)


def test_stale_item_can_be_retired_or_reengaged(db_session: Session) -> None:
    """Very old pending items are marked stale for explicit retire/re-engage decisions."""
    fixed_now = datetime(2026, 6, 1, 12, 0, 0, tzinfo=utc_now().tzinfo)
    stale = seed_new_learning_item(
        db_session,
        learner_id="learner-stale",
        knowledge_node_id="node-old",
        now=fixed_now - timedelta(days=90),
    )
    fresh = seed_new_learning_item(
        db_session,
        learner_id="learner-stale",
        knowledge_node_id="node-fresh",
        now=fixed_now - timedelta(days=2),
    )

    count = mark_stale_queue_items(
        db_session,
        learner_id="learner-stale",
        stale_after_days=45,
        now=fixed_now,
    )

    assert count == 1
    assert stale.reason_code == "stale"
    assert stale.priority == 0.3
    assert "Re-engage it, retire it, or adjust the learning goal" in stale.reason_explanation
    assert stale.decision_log["events"][-1]["rule"] == "mark-stale"
    assert fresh.reason_code == "new-learning"
