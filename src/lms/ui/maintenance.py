"""Learner surfaces for the workplace knowledge-maintenance strand."""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from html import escape
from typing import Annotated
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from lms.db.session import get_session
from lms.learners.identity import LearnerIdDep
from lms.learners.models import Learner
from lms.maintenance.anchors import AnchorSpec, parse_reading
from lms.maintenance.budget import BudgetSettings, describe, estimate_capacity
from lms.maintenance.drafts import count_pending_drafts
from lms.maintenance.models import PRECISION_MODES, MaintenanceItem
from lms.maintenance.service import (
    count_active_items,
    list_due_items,
    record_dispute,
    retire_expired_items,
    set_item_tier,
    submit_review,
    tier_counts,
)
from lms.scheduling.fsrs_engine import RETENTION_TIERS
from lms.ui.shell import empty_state, render_page

router = APIRouter(tags=["maintenance-ui"])
SessionDep = Annotated[Session, Depends(get_session)]

MAINTENANCE_PATH = "/app/learner/maintenance"
REVIEW_PATH = f"{MAINTENANCE_PATH}/review"
DISPUTE_PATH = f"{MAINTENANCE_PATH}/dispute"
DRAFTS_LINK = f"{MAINTENANCE_PATH}/drafts"
ITEM_PATH = f"{MAINTENANCE_PATH}/item"
BUDGET_PATH = f"{MAINTENANCE_PATH}/budget"


@router.get(MAINTENANCE_PATH, response_class=HTMLResponse)
def maintenance_home_route(session: SessionDep, learner_id: LearnerIdDep) -> str:
    """List what is due today."""
    # Retire anything whose relevance horizon has passed before counting, so
    # capacity and utilisation are computed from items that still matter.
    retired = retire_expired_items(session, learner_id=learner_id)
    if retired:
        session.commit()
    due = list_due_items(session, learner_id=learner_id)
    total = count_active_items(session, learner_id=learner_id)
    pending = count_pending_drafts(session, learner_id=learner_id)
    retired_note = (
        f"<p class='note'>{len(retired)} item(s) passed their relevance horizon and were "
        "retired.</p>"
        if retired
        else ""
    )
    budget_note = _budget_panel(session, learner_id=learner_id, active_items=total)
    drafts_link = (
        f"<p class='note'><a href='{DRAFTS_LINK}'>{pending} draft(s) awaiting approval</a>"
        " — nothing is scheduled until you approve it.</p>"
        if pending
        else ""
    )
    if not due:
        body = empty_state(
            "Nothing due right now",
            f"You have {total} active item(s). They come back when their next review "
            "is due — nothing here means nothing needs attention today.",
        )
        return _page("Maintenance", retired_note + budget_note + drafts_link + body)

    rows = "".join(
        "<li class='panel-item'>"
        f"<strong>{escape(entry.item.title)}</strong>"
        f"<span>{escape(_type_label(entry.item))} · {escape(entry.item.retention_tier)} tier</span>"
        f"<small>{escape(entry.item.subject_label or 'unfiled')}</small>"
        f"<a href='{REVIEW_PATH}?item_id={escape(entry.item.id)}'>Review this</a> "
        f"<a href='{ITEM_PATH}?item_id={escape(entry.item.id)}'>Adjust</a>"
        "</li>"
        for entry in due
    )
    body = (
        retired_note
        + budget_note
        + drafts_link
        + f"<p>{len(due)} of {total} item(s) due. Counts are informational, not an obligation.</p>"
        f"<ul class='panel-list'>{rows}</ul>"
    )
    return _page("Maintenance", body)


@router.get(REVIEW_PATH, response_class=HTMLResponse)
def maintenance_review_route(
    session: SessionDep,
    learner_id: LearnerIdDep,
    item_id: Annotated[str, Query(min_length=1, max_length=36)],
) -> str:
    """Show one item's prompt and an answer box."""
    item = _load_item(session, item_id=item_id, learner_id=learner_id)
    return _page("Maintenance review", _question_form(item))


@router.post(REVIEW_PATH, response_class=HTMLResponse)
async def submit_maintenance_review_route(
    request: Request, session: SessionDep, learner_id: LearnerIdDep
) -> str:
    """Grade the answer, schedule the next review, and show the verdict."""
    form = _read_form((await request.body()).decode())
    item = _load_item(session, item_id=form.get("item_id", ""), learner_id=learner_id)
    answer = (form.get("answer") or "").strip()
    if not answer:
        return _page(
            "Maintenance review",
            _question_form(item, error="Write an answer before submitting."),
        )

    reading = parse_reading(form.get("reading", "")) if form.get("reading") else None
    result, card = submit_review(session, item=item, answer=answer, reading=reading)
    session.commit()

    verdict = "Correct" if result.passed else "Not quite"
    percent = f"{result.score:.0%}"
    grader = escape(str(result.detail.get("grader", "deterministic")))
    return _page(
        "Maintenance review",
        f"""
        <section aria-labelledby="verdict-heading">
          <h2 id="verdict-heading">{escape(verdict)} — {escape(percent)}</h2>
          <p class="score">{escape(result.explanation)}</p>
          <p class="note">Graded by: {grader}. Next review {escape(_due_label(card))}.</p>
        </section>
        <section aria-labelledby="your-answer-heading">
          <h2 id="your-answer-heading">Your answer</h2>
          <p class="attempt-response">{escape(answer)}</p>
        </section>
        {_dispute_form(item=item, answer=answer, machine_grade=result.score)}
        <p class="back-link"><a href="{MAINTENANCE_PATH}">Back to maintenance</a></p>
        """,
    )


@router.post(DISPUTE_PATH, response_class=HTMLResponse)
async def dispute_grade_route(
    request: Request, session: SessionDep, learner_id: LearnerIdDep
) -> str:
    """Record disagreement with a grade and re-rate the item."""
    form = _read_form((await request.body()).decode())
    item = _load_item(session, item_id=form.get("item_id", ""), learner_id=learner_id)
    learner_grade = _grade_choice(form.get("learner_grade"))
    record_dispute(
        session,
        item=item,
        answer=form.get("answer", ""),
        machine_grade=_float_or_none(form.get("machine_grade")),
        learner_grade=learner_grade,
        comment=(form.get("comment") or "").strip() or None,
    )
    session.commit()
    note = (
        "Recorded, and the item was rescheduled using your grade."
        if learner_grade is not None
        else "Recorded. Your note will inform how these are graded."
    )
    return _page(
        "Maintenance review",
        f"""
        <section aria-labelledby="dispute-heading">
          <h2 id="dispute-heading">Thanks — noted</h2>
          <p>{escape(note)}</p>
        </section>
        <p class="back-link"><a href="{MAINTENANCE_PATH}">Back to maintenance</a></p>
        """,
    )


# --- rendering helpers ----------------------------------------------------


def _question_form(item: MaintenanceItem, *, error: str | None = None) -> str:
    """Render the prompt plus the right answer control for the item type."""
    error_block = f"<p role='alert' class='error'>{escape(error)}</p>" if error else ""
    reading_block = ""
    hint = ""
    if item.item_type == "reference_anchor":
        spec = AnchorSpec.from_payload(item.payload)
        hint = (
            f"<p class='note'>Answer in {escape(spec.unit)}. Graded on "
            f"{escape(item.precision_mode)} — being roughly right is the point.</p>"
        )
        reading_block = (
            "<label for='reading'>Optional: a current reading to judge against"
            "<input type='text' id='reading' name='reading' "
            "placeholder='e.g. 60'></label>"
        )
    source = (
        f"<p class='note'>Source: {escape(item.source_locator_hint)}</p>"
        if item.source_locator_hint
        else ""
    )
    return f"""
    <section aria-labelledby="prompt-heading">
      <h2 id="prompt-heading">{escape(item.title)}</h2>
      <p>{escape(item.prompt)}</p>
      {hint}
    </section>
    {error_block}
    <form method="post" action="{REVIEW_PATH}">
      <input type="hidden" name="item_id" value="{escape(item.id)}">
      <label for="answer">Your answer
        <textarea id="answer" name="answer" rows="5" required></textarea>
      </label>
      {reading_block}
      <button type="submit">Submit answer</button>
    </form>
    {source}
    <p class="back-link"><a href="{MAINTENANCE_PATH}">Back to maintenance</a></p>
    """


def _dispute_form(*, item: MaintenanceItem, answer: str, machine_grade: float) -> str:
    """Let the learner push back on a grade they think is wrong."""
    return f"""
    <section aria-labelledby="dispute-form-heading" class="dispute">
      <h2 id="dispute-form-heading">Graded wrong?</h2>
      <form method="post" action="{DISPUTE_PATH}">
        <input type="hidden" name="item_id" value="{escape(item.id)}">
        <input type="hidden" name="answer" value="{escape(answer)}">
        <input type="hidden" name="machine_grade" value="{machine_grade:.4f}">
        <label for="learner_grade">How should it have been graded?
          <select id="learner_grade" name="learner_grade">
            <option value="">(just leave a note)</option>
            <option value="correct">I had it</option>
            <option value="partial">Partly</option>
            <option value="incorrect">I did not have it</option>
          </select>
        </label>
        <label for="comment">What did the grader get wrong?
          <textarea id="comment" name="comment" rows="2"></textarea>
        </label>
        <button type="submit">Send feedback</button>
      </form>
    </section>
    """


_GRADE_VALUES: dict[str, float] = {"correct": 1.0, "partial": 0.6, "incorrect": 0.0}


def _grade_choice(value: str | None) -> float | None:
    return _GRADE_VALUES.get(value or "")


def _float_or_none(value: str | None) -> float | None:
    try:
        return float(value) if value else None
    except ValueError:
        return None


def _type_label(item: MaintenanceItem) -> str:
    return "reference anchor" if item.item_type == "reference_anchor" else "idea"


def _due_label(card: object) -> str:
    due = getattr(card, "due_at", None)
    return f"scheduled for {due:%a %d %b %Y}" if due is not None else "scheduled"


def _load_item(session: Session, *, item_id: str, learner_id: str) -> MaintenanceItem:
    item = session.get(MaintenanceItem, item_id)
    if item is None or item.learner_id != learner_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Maintenance item not found for this learner.",
        )
    return item


def _read_form(body: str) -> dict[str, str]:
    raw = parse_qs(body, keep_blank_values=True)
    return {key: values[-1] for key, values in raw.items()}


def _page(eyebrow: str, body: str) -> str:
    return render_page(
        "Maintenance",
        f"""
        <main class="surface maintenance-surface">
          <header>
            <p class="eyebrow">{escape(eyebrow)}</p>
            <h1>Keep it reachable</h1>
          </header>
          {body}
        </main>
        """,
        active_path="/app/learner",
    )


def _budget_panel(session: Session, *, learner_id: str, active_items: int) -> str:
    """Show what the current budget carries, and let the owner change it."""
    learner = session.get(Learner, learner_id)
    settings = BudgetSettings(
        daily_minutes=getattr(learner, "daily_minutes_target", 10) or 10,
        daily_item_cap=getattr(learner, "daily_item_cap", 25) or 25,
    )
    estimate = estimate_capacity(
        settings,
        active_items=active_items,
        tier_counts=tier_counts(session, learner_id=learner_id),
    )
    warning = (
        "<p role='status' class='error'>You are at or over capacity — adding items now "
        "will crowd out what you already keep.</p>"
        if estimate.at_capacity
        else ""
    )
    return f"""
    <section class="budget-panel" aria-labelledby="budget-heading">
      <h2 id="budget-heading">Your budget</h2>
      <p>{escape(describe(estimate))}</p>
      {warning}
      <form method="post" action="{BUDGET_PATH}">
        <label for="daily_minutes">Minutes a day
          <input type="number" id="daily_minutes" name="daily_minutes" min="1" max="240"
                 value="{settings.daily_minutes}">
        </label>
        <label for="daily_item_cap">Most items in one day
          <input type="number" id="daily_item_cap" name="daily_item_cap" min="1" max="200"
                 value="{settings.daily_item_cap}">
        </label>
        <button type="submit">Update budget</button>
      </form>
    </section>
    """


@router.post(BUDGET_PATH)
async def update_budget_route(
    request: Request, session: SessionDep, learner_id: LearnerIdDep
) -> RedirectResponse:
    """Update the learner's review budget."""
    form = _read_form((await request.body()).decode())
    learner = session.get(Learner, learner_id)
    if learner is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Learner not found.")
    minutes = _bounded_int(form.get("daily_minutes"), low=1, high=240)
    cap = _bounded_int(form.get("daily_item_cap"), low=1, high=200)
    if minutes is not None:
        learner.daily_minutes_target = minutes
    if cap is not None:
        learner.daily_item_cap = cap
    session.commit()
    return RedirectResponse(url=MAINTENANCE_PATH, status_code=status.HTTP_303_SEE_OTHER)


@router.get(ITEM_PATH, response_class=HTMLResponse)
def item_settings_route(
    session: SessionDep,
    learner_id: LearnerIdDep,
    item_id: Annotated[str, Query(min_length=1, max_length=36)],
) -> str:
    """Adjust one item's tier, precision and horizon outside the review flow."""
    item = _load_item(session, item_id=item_id, learner_id=learner_id)
    tiers = "".join(
        f"<option value='{escape(tier)}'"
        f"{' selected' if tier == item.retention_tier else ''}>{escape(tier)}</option>"
        for tier in RETENTION_TIERS
    )
    modes = "".join(
        f"<option value='{escape(mode)}'"
        f"{' selected' if mode == item.precision_mode else ''}>{escape(mode)}</option>"
        for mode in PRECISION_MODES
    )
    horizon = item.relevant_until.date().isoformat() if item.relevant_until else ""
    return _page(
        "Adjust item",
        f"""
        <section aria-labelledby="item-heading">
          <h2 id="item-heading">{escape(item.title)}</h2>
          <p class="note">{escape(item.subject_label or "unfiled")} ·
          {escape(_type_label(item))}</p>
        </section>
        <form method="post" action="{ITEM_PATH}">
          <input type="hidden" name="item_id" value="{escape(item.id)}">
          <label for="tier">Retention tier
            <select id="tier" name="retention_tier">{tiers}</select>
          </label>
          <label for="mode">Grading precision
            <select id="mode" name="precision_mode">{modes}</select>
          </label>
          <label for="horizon">Stop reviewing after (optional)
            <input type="date" id="horizon" name="relevant_until" value="{escape(horizon)}">
          </label>
          <button type="submit">Save</button>
        </form>
        <form method="post" action="{ITEM_PATH}/retire">
          <input type="hidden" name="item_id" value="{escape(item.id)}">
          <button type="submit">Retire this item now</button>
        </form>
        <p class="back-link"><a href="{MAINTENANCE_PATH}">Back to maintenance</a></p>
        """,
    )


@router.post(ITEM_PATH)
async def save_item_settings_route(
    request: Request, session: SessionDep, learner_id: LearnerIdDep
) -> RedirectResponse:
    """Persist tier, precision and horizon changes."""
    form = _read_form((await request.body()).decode())
    item = _load_item(session, item_id=form.get("item_id", ""), learner_id=learner_id)
    tier = form.get("retention_tier")
    if tier in RETENTION_TIERS:
        set_item_tier(session, item=item, retention_tier=tier)
    mode = form.get("precision_mode")
    if mode in PRECISION_MODES:
        item.precision_mode = mode
    raw_horizon = (form.get("relevant_until") or "").strip()
    if raw_horizon:
        with contextlib.suppress(ValueError):
            item.relevant_until = datetime.fromisoformat(raw_horizon).replace(tzinfo=UTC)
    else:
        item.relevant_until = None
    session.commit()
    return RedirectResponse(url=MAINTENANCE_PATH, status_code=status.HTTP_303_SEE_OTHER)


@router.post(f"{ITEM_PATH}/retire")
async def retire_item_route(
    request: Request, session: SessionDep, learner_id: LearnerIdDep
) -> RedirectResponse:
    """Retire one item immediately."""
    form = _read_form((await request.body()).decode())
    item = _load_item(session, item_id=form.get("item_id", ""), learner_id=learner_id)
    item.status = "retired"
    session.commit()
    return RedirectResponse(url=MAINTENANCE_PATH, status_code=status.HTTP_303_SEE_OTHER)


def _bounded_int(raw: str | None, *, low: int, high: int) -> int | None:
    try:
        value = int((raw or "").strip())
    except ValueError:
        return None
    return max(low, min(high, value))
