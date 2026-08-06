"""Learner surfaces for the workplace knowledge-maintenance strand."""

from __future__ import annotations

from html import escape
from typing import Annotated
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from lms.db.session import get_session
from lms.learners.identity import LearnerIdDep
from lms.maintenance.anchors import AnchorSpec, parse_reading
from lms.maintenance.models import MaintenanceItem
from lms.maintenance.service import (
    count_active_items,
    list_due_items,
    record_dispute,
    submit_review,
)
from lms.ui.shell import empty_state, render_page

router = APIRouter(tags=["maintenance-ui"])
SessionDep = Annotated[Session, Depends(get_session)]

MAINTENANCE_PATH = "/app/learner/maintenance"
REVIEW_PATH = f"{MAINTENANCE_PATH}/review"
DISPUTE_PATH = f"{MAINTENANCE_PATH}/dispute"


@router.get(MAINTENANCE_PATH, response_class=HTMLResponse)
def maintenance_home_route(session: SessionDep, learner_id: LearnerIdDep) -> str:
    """List what is due today."""
    due = list_due_items(session, learner_id=learner_id)
    total = count_active_items(session, learner_id=learner_id)
    if not due:
        body = empty_state(
            "Nothing due right now",
            f"You have {total} active item(s). They come back when their next review "
            "is due — nothing here means nothing needs attention today.",
        )
        return _page("Maintenance", body)

    rows = "".join(
        "<li class='panel-item'>"
        f"<strong>{escape(entry.item.title)}</strong>"
        f"<span>{escape(_type_label(entry.item))} · {escape(entry.item.retention_tier)} tier</span>"
        f"<small>{escape(entry.item.subject_label or 'unfiled')}</small>"
        f"<a href='{REVIEW_PATH}?item_id={escape(entry.item.id)}'>Review this</a>"
        "</li>"
        for entry in due
    )
    body = (
        f"<p>{len(due)} of {total} item(s) due. Counts are informational, not an obligation.</p>"
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
