"""How the learner UI renders a due date.

`_learner_zone`'s docstring names the bug these helpers exist to prevent: scheduling stores UTC,
and rendering UTC to a learner in a western timezone made "due today" read as tomorrow's date.
None of it was tested — which is the usual shape of a timezone defect, because every assertion
written in the machine's own timezone passes.

So the tests below are written across zones on purpose. The one that matters most puts a due time
late enough in the UTC day that a western learner is still on the previous local date, and asserts
they are told "today" while a UTC learner is told "tomorrow". Both are correct; a single answer for
both is the defect.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.orm import Session

from lms.auth.models import User
from lms.learners.repository import create_learner_for_user
from lms.ui.api import (
    _as_utc,
    _learner_zone,
    _local_day,
    _optional_detail,
    _queue_status_label,
    _relative_day,
)

_NOW = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
_UTC_ZONE = ZoneInfo("UTC")
_WEST = ZoneInfo("America/Los_Angeles")  # UTC-7 on this date


# ---------------------------------------------------------------------------------------------
# Relative days, the way a person says them.
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "days,expected",
    [
        (0, "today"),
        (1, "tomorrow"),
        (-1, "yesterday"),
        (-3, "3 days ago"),
        (-30, "30 days ago"),
        (2, "in 2 days"),
        (14, "in 14 days"),
    ],
)
def test_a_nearby_due_date_is_phrased_relatively(days, expected):
    assert _relative_day(_NOW + timedelta(days=days), _UTC_ZONE, now=_NOW) == expected


def test_beyond_a_fortnight_the_actual_date_is_shown():
    """ "in 47 days" is not something a person can act on; a date is."""
    assert _relative_day(_NOW + timedelta(days=15), _UTC_ZONE, now=_NOW) == "Tue 15 Sep 2026"


def test_fourteen_days_is_the_last_relative_answer():
    """The boundary itself, so an off-by-one in either direction shows."""
    assert _relative_day(_NOW + timedelta(days=14), _UTC_ZONE, now=_NOW) == "in 14 days"
    assert _relative_day(_NOW + timedelta(days=15), _UTC_ZONE, now=_NOW) != "in 15 days"


def test_an_absent_due_date_reads_as_unknown_not_as_today():
    """`None` is "not scheduled". Rendering it as today would put unscheduled work in front of a
    learner every single day."""
    assert _relative_day(None, _UTC_ZONE, now=_NOW) == "unknown"
    assert _local_day(None, _UTC_ZONE) == "unknown"


# ---------------------------------------------------------------------------------------------
# ...in the learner's timezone, which is the whole point.
# ---------------------------------------------------------------------------------------------


def test_the_same_instant_is_today_in_one_zone_and_tomorrow_in_another():
    """The documented defect, stated directly.

    02:00 UTC on 1 September is 19:00 on 31 August in Los Angeles. Relative to 12:00 UTC on
    31 August — 05:00 local — a western learner's item is due TODAY, while a UTC learner's is due
    tomorrow. Both are right, and a single answer for both is the bug the helper exists to avoid.
    """
    due = datetime(2026, 9, 1, 2, 0, tzinfo=UTC)

    assert _relative_day(due, _WEST, now=_NOW) == "today"
    assert _relative_day(due, _UTC_ZONE, now=_NOW) == "tomorrow"


def test_the_reference_day_is_the_learners_today_not_the_servers():
    """The other half of the conversion, and the half a same-day fixture cannot reach.

    At 02:00 UTC on 1 September it is still the EVENING of 31 August in Los Angeles. An item due
    at 03:00 UTC — 20:00 the same local evening — is due today for that learner. Converting the
    due time to their zone while leaving "now" in UTC compares 31 August against 1 September and
    reports the item as overdue, which is how a due-today task becomes a missed one.
    """
    now = datetime(2026, 9, 1, 2, 0, tzinfo=UTC)
    due = datetime(2026, 9, 1, 3, 0, tzinfo=UTC)

    assert _relative_day(due, _WEST, now=now) == "today"


def test_the_rendered_date_follows_the_learners_zone_too():
    """`_local_day` and `_relative_day` must not disagree about which day it is."""
    due = datetime(2026, 9, 1, 2, 0, tzinfo=UTC)

    assert _local_day(due, _WEST) == "Mon 31 Aug 2026"
    assert _local_day(due, _UTC_ZONE) == "Tue 1 Sep 2026"


def test_a_naive_timestamp_is_read_as_utc():
    """SQLite reads datetimes back without tzinfo. Treating those as LOCAL would shift every
    stored due date by the server's offset — invisibly, and only on some machines."""
    naive = datetime(2026, 8, 31, 23, 30)

    assert _as_utc(naive) == datetime(2026, 8, 31, 23, 30, tzinfo=UTC)
    assert _relative_day(naive, _UTC_ZONE, now=_NOW) == "today"


def test_an_aware_timestamp_is_left_alone():
    aware = datetime(2026, 8, 31, 23, 30, tzinfo=ZoneInfo("Europe/Berlin"))
    assert _as_utc(aware) is aware


# ---------------------------------------------------------------------------------------------
# Resolving the learner's zone.
# ---------------------------------------------------------------------------------------------


def _learner(session: Session, suffix: str, timezone: str) -> str:
    user = User(
        email=f"zone-{suffix}@example.test", username=f"zone-{suffix}", display_name="Learner"
    )
    session.add(user)
    session.flush()
    return create_learner_for_user(
        session, user_id=user.id, display_name="Learner", timezone=timezone
    ).id


def test_a_configured_timezone_is_used(db_session: Session):
    learner_id = _learner(db_session, "configured", "America/Los_Angeles")
    assert _learner_zone(db_session, learner_id) == _WEST


def test_an_unknown_timezone_falls_back_to_utc_rather_than_raising(db_session: Session):
    """A stale or mistyped zone name must degrade to UTC. Raising here takes down the dashboard
    for a bad string in one profile row."""
    learner_id = _learner(db_session, "bogus", "Mars/Olympus_Mons")
    assert _learner_zone(db_session, learner_id) == ZoneInfo("UTC")


def test_a_missing_learner_falls_back_to_utc(db_session: Session):
    assert _learner_zone(db_session, "no-such-learner") == ZoneInfo("UTC")


# ---------------------------------------------------------------------------------------------
# Queue labels and optional detail.
# ---------------------------------------------------------------------------------------------


def test_a_blocked_prerequisite_overrides_the_pending_status():
    """`pending` renders as "available", so a blocked item would otherwise invite a learner to
    start work they cannot do."""
    assert _queue_status_label("pending", "blocked-prerequisite") == "blocked"


def test_a_pending_item_reads_as_available():
    assert _queue_status_label("pending", "ready") == "available"


def test_any_other_status_is_shown_as_it_is():
    assert _queue_status_label("completed", "ready") == "completed"
    assert _queue_status_label("skipped", "ready") == "skipped"


def test_a_blocked_prerequisite_wins_over_every_status():
    """The reason code is checked first. Reordering would let a non-pending status hide the
    blockage."""
    assert _queue_status_label("completed", "blocked-prerequisite") == "blocked"


def test_optional_detail_is_omitted_when_there_is_no_value():
    assert _optional_detail("note", None) == ""
    assert _optional_detail("note", "") == ""


def test_optional_detail_escapes_the_value_it_renders():
    """The value reaches an HTML page. Unescaped, a note containing markup is script injection
    through a field a learner controls."""
    rendered = _optional_detail("note", "<script>alert(1)</script>")

    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered


def test_optional_detail_escapes_the_label_too():
    """Labels are code-supplied today, which is exactly why an unescaped one would go unnoticed
    until the day one is not."""
    assert "<b>" not in _optional_detail("<b>note</b>", "value")
