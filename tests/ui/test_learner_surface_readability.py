"""Readability gates for the learner surfaces (audit LMS-R18/R19/R20/R21).

The observed UX drive on 2026-08-01 found the daily surfaces technically
correct but hard to actually read: review items identified by raw UUIDs,
UTC timestamps that render as tomorrow's date for a US-based reader, and a
dashboard showing ~30 byte-identical "next action" rows. These tests pin the
fixes so the surfaces cannot silently regress to id-dumping.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from lms.ui import api as ui_api


class _StubAction:
    """Minimal stand-in for FeedbackAction in panel rendering."""

    def __init__(
        self,
        *,
        title: str,
        action_type: str = "retry",
        status: str = "open",
        due_at: datetime | None = None,
        instructions: str | None = None,
    ) -> None:
        self.title = title
        self.action_type = action_type
        self.status = status
        self.due_at = due_at
        self.instructions = instructions


def test_identical_next_actions_collapse_into_a_counted_row() -> None:
    """Thirty identical follow-ups render as one row with a tally, not thirty."""
    actions = [_StubAction(title="Schedule a follow-up review") for _ in range(30)]

    html = ui_api._next_actions_panel(actions, zone=ZoneInfo("UTC"))

    assert html.count("Schedule a follow-up review") == 1
    assert "×30" in html


def test_distinct_next_actions_are_not_merged() -> None:
    """Grouping must not hide genuinely different actions."""
    actions = [
        _StubAction(title="Schedule a follow-up review"),
        _StubAction(title="Re-read the prerequisite", action_type="prerequisite-remediation"),
    ]

    html = ui_api._next_actions_panel(actions, zone=ZoneInfo("UTC"))

    assert "Schedule a follow-up review" in html
    assert "Re-read the prerequisite" in html
    assert "×" not in html, "single-instance actions should carry no tally"


def test_due_dates_render_in_the_learner_timezone_not_utc() -> None:
    """A late-evening US 'today' must not display as tomorrow.

    19:00 in Chicago on 2 Aug is 00:00 UTC on 3 Aug; rendering the raw UTC
    date told the reader their review was due tomorrow when it was due now.
    """
    chicago = ZoneInfo("America/Chicago")
    now = datetime(2026, 8, 3, 0, 0, tzinfo=UTC)  # 2 Aug, 19:00 in Chicago

    assert ui_api._relative_day(now, chicago, now=now) == "today"
    assert ui_api._relative_day(now + timedelta(days=1), chicago, now=now) == "tomorrow"
    assert ui_api._relative_day(now - timedelta(days=1), chicago, now=now) == "yesterday"


def test_relative_day_falls_back_to_a_readable_date_when_far_out() -> None:
    """Long-horizon items (now possible under FSRS) get a real date, not 'in 400 days'."""
    zone = ZoneInfo("UTC")
    now = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)

    label = ui_api._relative_day(now + timedelta(days=200), zone, now=now)

    assert "2027" in label
    assert "in 200 days" not in label


def test_naive_datetimes_are_treated_as_utc() -> None:
    """SQLite returns naive datetimes; they must not shift the displayed day."""
    zone = ZoneInfo("UTC")
    now = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)
    naive = datetime(2026, 8, 3, 12, 0)

    assert ui_api._relative_day(naive, zone, now=now) == "today"


def test_node_label_prefers_a_title_over_a_raw_uuid() -> None:
    """Queue and evidence rows show topic titles, with a graceful fallback."""
    titles = {"11111111-2222-3333-4444-555555555555": "Key-man provisions"}

    assert (
        ui_api._node_label("11111111-2222-3333-4444-555555555555", titles) == "Key-man provisions"
    )
    # Unknown ids degrade to a short id rather than vanishing.
    label = ui_api._node_label("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", titles)
    assert label == "node aaaaaaaa"
    assert "eeeeeeee" not in label


def test_feedback_lists_have_block_level_fields() -> None:
    """The feedback CSS must stack fields, or they concatenate on screen.

    Observed as "Record learner attemptTopic 01 concerns..." — two separate
    fields reading as one corrupted string (audit LMS-R20).
    """
    css = ui_api._STATIC_FILES.joinpath("app.css").read_text()  # type: ignore[attr-defined]
    assert ".feedback-records li strong" in css
    assert ".feedback-actions li strong" in css


def test_design_system_styles_password_inputs() -> None:
    """The login password field must get the same treatment as username."""
    css = ui_api._STATIC_FILES.joinpath("components.css").read_text()  # type: ignore[attr-defined]
    assert "input[type=password]" in css
