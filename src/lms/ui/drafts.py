"""Draft approval surface.

Separates the two review jobs on screen: transcribed fields are shown beside
the source snippet for a quick check, while inferred fields (the band, the
tolerance, the tier) are presented as editable judgments, because those are
not in the source and they decide how the item grades for years.
"""

from __future__ import annotations

from html import escape
from typing import Annotated
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from lms.db.session import get_session
from lms.learners.identity import LearnerIdDep
from lms.maintenance.drafts import (
    PENDING_DRAFT_CAP,
    DraftView,
    approve_draft,
    count_pending_drafts,
    expire_stale_drafts,
    list_pending_drafts,
    reject_draft,
    remaining_draft_capacity,
)
from lms.maintenance.models import MaintenanceItem
from lms.scheduling.fsrs_engine import RETENTION_TIERS
from lms.ui.shell import empty_state, render_page

router = APIRouter(tags=["maintenance-ui"])
SessionDep = Annotated[Session, Depends(get_session)]

DRAFTS_PATH = "/app/learner/maintenance/drafts"
APPROVE_PATH = f"{DRAFTS_PATH}/approve"
REJECT_PATH = f"{DRAFTS_PATH}/reject"
BULK_PATH = f"{DRAFTS_PATH}/approve-ideas"


@router.get(DRAFTS_PATH, response_class=HTMLResponse)
def drafts_home_route(session: SessionDep, learner_id: LearnerIdDep) -> str:
    """List drafts awaiting a decision."""
    lapsed = expire_stale_drafts(session, learner_id=learner_id)
    if lapsed:
        session.commit()
    drafts = list_pending_drafts(session, learner_id=learner_id)
    pending = count_pending_drafts(session, learner_id=learner_id)
    remaining = remaining_draft_capacity(session, learner_id=learner_id)

    lapsed_note = (
        f"<p class='note'>{lapsed} draft(s) lapsed unreviewed and were cleared.</p>"
        if lapsed
        else ""
    )
    if not drafts:
        return _page(
            "Approve drafts",
            lapsed_note
            + empty_state(
                "No drafts waiting",
                "Nothing is proposed right now. Drafted items appear here before they "
                "can ever be scheduled.",
            ),
        )

    ideas = [view for view in drafts if not view.needs_individual_review]
    anchors = [view for view in drafts if view.needs_individual_review]
    bulk = _bulk_ideas_block(ideas) if ideas else ""
    anchor_blocks = "".join(_draft_card(view) for view in anchors)
    idea_blocks = "".join(_draft_card(view) for view in ideas)

    return _page(
        "Approve drafts",
        f"""
        {lapsed_note}
        <p>{pending} draft(s) waiting; {remaining} slot(s) left of {PENDING_DRAFT_CAP}
        before drafting pauses. Nothing here is scheduled until you approve it.</p>
        {bulk}
        {anchor_blocks}
        {idea_blocks}
        <p class="back-link"><a href="/app/learner/maintenance">Back to maintenance</a></p>
        """,
    )


@router.post(APPROVE_PATH)
async def approve_draft_route(
    request: Request, session: SessionDep, learner_id: LearnerIdDep
) -> RedirectResponse:
    """Approve one draft, applying edits made during review."""
    form = _read_form((await request.body()).decode())
    item = _load_draft(session, item_id=form.get("item_id", ""), learner_id=learner_id)

    edits: dict[str, object] = {}
    for key, raw in form.items():
        if not key.startswith("payload."):
            continue
        field = key.removeprefix("payload.")
        current = item.payload.get(field)
        parsed = _coerce_like(current, raw)
        if parsed is not None and parsed != current:
            edits[field] = parsed

    approve_draft(
        session,
        item=item,
        payload_edits=edits or None,
        retention_tier=form.get("retention_tier") or None,
        precision_mode=form.get("precision_mode") or None,
    )
    session.commit()
    return RedirectResponse(url=DRAFTS_PATH, status_code=status.HTTP_303_SEE_OTHER)


@router.post(BULK_PATH)
async def bulk_approve_ideas_route(
    request: Request, session: SessionDep, learner_id: LearnerIdDep
) -> RedirectResponse:
    """Approve every pending idea draft at once.

    Only ideas. Reference anchors carry memorisable numbers and always
    require an individual look at the source snippet.
    """
    # parse_qs keeps every repeated key, which _read_form collapses -- bulk
    # approval needs all of them, so parse the body once and read the list.
    raw = parse_qs((await request.body()).decode(), keep_blank_values=True)
    ids = {value for value in raw.get("item_id", []) if value}
    for item_id in ids:
        item = session.get(MaintenanceItem, item_id)
        if item is None or item.learner_id != learner_id or item.status != "draft":
            continue
        if item.item_type == "reference_anchor":
            continue
        approve_draft(session, item=item)
    session.commit()
    return RedirectResponse(url=DRAFTS_PATH, status_code=status.HTTP_303_SEE_OTHER)


@router.post(REJECT_PATH)
async def reject_draft_route(
    request: Request, session: SessionDep, learner_id: LearnerIdDep
) -> RedirectResponse:
    """Discard a draft, keeping the reason when one is given."""
    form = _read_form((await request.body()).decode())
    item = _load_draft(session, item_id=form.get("item_id", ""), learner_id=learner_id)
    reject_draft(session, item=item, reason=form.get("reason"))
    session.commit()
    return RedirectResponse(url=DRAFTS_PATH, status_code=status.HTTP_303_SEE_OTHER)


# --- rendering ------------------------------------------------------------


def _draft_card(view: DraftView) -> str:
    item = view.item
    source = (
        f"<p class='note source-quote'>Source: {escape(item.source_locator_hint)}</p>"
        if item.source_locator_hint
        else "<p class='note'>No source recorded for this draft.</p>"
    )
    verify = (
        "<ul class='panel-list verify-list'>"
        + "".join(
            f"<li class='panel-item'><strong>{escape(field.name)}</strong>"
            f"<span>{escape(_fmt(field.value))}</span></li>"
            for field in view.transcribed
        )
        + "</ul>"
        if view.transcribed
        else "<p class='note'>Nothing transcribed from the source.</p>"
    )
    judge = "".join(
        f"<label for='{escape(item.id)}-{escape(field.name)}'>{escape(field.name)}"
        f"<input type='text' id='{escape(item.id)}-{escape(field.name)}' "
        f"name='payload.{escape(field.name)}' value='{escape(_fmt(field.value))}'></label>"
        for field in view.inferred
    )
    tiers = "".join(
        f"<option value='{escape(tier)}'"
        f"{' selected' if tier == item.retention_tier else ''}>{escape(tier)}</option>"
        for tier in RETENTION_TIERS
    )
    return f"""
    <section class="draft-card" aria-labelledby="draft-{escape(item.id)}">
      <h2 id="draft-{escape(item.id)}">{escape(item.title)}</h2>
      <p>{escape(item.prompt)}</p>
      {source}
      <h3>Check against the source</h3>
      {verify}
      <h3>Your judgment — not in the source</h3>
      <form method="post" action="{APPROVE_PATH}">
        <input type="hidden" name="item_id" value="{escape(item.id)}">
        {judge}
        <label for="{escape(item.id)}-tier">retention tier
          <select id="{escape(item.id)}-tier" name="retention_tier">{tiers}</select>
        </label>
        <button type="submit">Approve</button>
      </form>
      <form method="post" action="{REJECT_PATH}" class="reject-form">
        <input type="hidden" name="item_id" value="{escape(item.id)}">
        <label for="{escape(item.id)}-reason">Reject — why? (optional)
          <input type="text" id="{escape(item.id)}-reason" name="reason"
                 placeholder="e.g. not worth remembering">
        </label>
        <button type="submit">Reject</button>
      </form>
    </section>
    """


def _bulk_ideas_block(ideas: list[DraftView]) -> str:
    """Bulk-approve control for idea drafts only."""
    hidden = "".join(
        f"<input type='hidden' name='item_id' value='{escape(view.item.id)}'>" for view in ideas
    )
    titles = "".join(f"<li>{escape(view.item.title)}</li>" for view in ideas)
    return f"""
    <section class="bulk-approve" aria-labelledby="bulk-heading">
      <h2 id="bulk-heading">Approve all {len(ideas)} idea draft(s)</h2>
      <p class="note">Ideas can go through together — a weak key point just makes a
      question vaguer. Reference anchors are never bulk-approved: a wrong number
      would be memorised as fact.</p>
      <ul>{titles}</ul>
      <form method="post" action="{BULK_PATH}">
        {hidden}
        <button type="submit">Approve all ideas</button>
      </form>
    </section>
    """


def _fmt(value: object) -> str:
    if isinstance(value, float) and value == int(value):
        return str(int(value))
    if isinstance(value, list):
        return "; ".join(
            (
                f"{entry.get('label')} {entry.get('value')} ({entry.get('period')})"
                if isinstance(entry, dict)
                else str(entry)
            )
            for entry in value
        )
    return str(value)


def _coerce_like(current: object, raw: str) -> object | None:
    """Parse an edited field back to the type it had. None means 'unchanged'."""
    text = (raw or "").strip()
    if not text:
        return None
    if isinstance(current, bool):
        return text.lower() in {"true", "yes", "1"}
    if isinstance(current, (int, float)):
        try:
            return float(text)
        except ValueError:
            return None
    if isinstance(current, (list, dict)):
        # Structured fields (extremes) are not editable as free text here.
        return None
    return text


def _load_draft(session: Session, *, item_id: str, learner_id: str) -> MaintenanceItem:
    item = session.get(MaintenanceItem, item_id)
    if item is None or item.learner_id != learner_id or item.status != "draft":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found for this learner."
        )
    return item


def _read_form(body: str) -> dict[str, str]:
    raw = parse_qs(body, keep_blank_values=True)
    return {key: values[-1] for key, values in raw.items()}


def _page(eyebrow: str, body: str) -> str:
    return render_page(
        "Approve drafts",
        f"""
        <main class="surface drafts-surface">
          <header>
            <p class="eyebrow">{escape(eyebrow)}</p>
            <h1>Before it enters the loop</h1>
          </header>
          {body}
        </main>
        """,
        active_path="/app/learner",
    )


__all__ = ["router"]
