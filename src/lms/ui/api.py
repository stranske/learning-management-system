"""Minimal HTML surfaces for testing the learner loop."""

from __future__ import annotations

from html import escape
from typing import Annotated
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from lms.db.session import get_session
from lms.evidence.repository import create_attempt
from lms.evidence.schemas import AttemptCreate, StructuredFeedback
from lms.prompts.models import Prompt
from lms.scheduling.service import DEFAULT_DAILY_CAP, SchedulerSettings, get_review_queue_overview

router = APIRouter(tags=["learner-ui"])
SessionDep = Annotated[Session, Depends(get_session)]


@router.get("/learn", response_class=HTMLResponse)
def learn_surface_route(
    session: SessionDep,
    learner_id: Annotated[str, Query(min_length=1, max_length=36)] = "learner-1",
    prompt_id: Annotated[str | None, Query(min_length=1, max_length=36)] = None,
) -> str:
    """Return a mobile-friendly Learn surface wired to the attempt API."""
    prompt = session.get(Prompt, prompt_id) if prompt_id is not None else None
    prompt_body = _prompt_body(prompt) if prompt is not None else "No prompt selected."
    citations = _source_citation_items(prompt) if prompt is not None else []

    return _page(
        "Learn",
        f"""
        <main class="surface learn-surface">
          <header>
            <p class="eyebrow">Assigned next task</p>
            <h1>Learn</h1>
          </header>
          <section aria-labelledby="prompt-heading">
            <h2 id="prompt-heading">Prompt</h2>
            <p class="prompt-text">{escape(prompt_body)}</p>
          </section>
          <form class="attempt-form" method="post" action="/learn/attempts">
            <input type="hidden" name="learner_id" value="{escape(learner_id)}">
            <input type="hidden" name="prompt_id" value="{escape(prompt_id or '')}">
            <label for="response_text">Response</label>
            <textarea id="response_text" name="response_text" rows="6"></textarea>
            <label for="confidence_rating">Confidence</label>
            <select id="confidence_rating" name="confidence_rating">
              <option value="1">1 - unsure</option>
              <option value="2">2</option>
              <option value="3">3</option>
              <option value="4">4</option>
              <option value="5">5 - confident</option>
            </select>
            <label class="check">
              <input type="checkbox" name="reference_accessed" value="true">
              I opened a reference during the attempt
            </label>
            <button type="submit">Submit attempt</button>
          </form>
          <section aria-labelledby="feedback-heading">
            <h2 id="feedback-heading">Feedback and next action</h2>
            <p>Feedback appears after an attempt is recorded through the attempts API.</p>
          </section>
          <section aria-labelledby="sources-heading" class="source-panel">
            <h2 id="sources-heading">Source citations after attempt</h2>
            <ul>{''.join(citations) if citations else '<li>No source citations linked.</li>'}</ul>
          </section>
        </main>
        """,
    )


@router.post("/learn/attempts", response_class=HTMLResponse)
async def submit_learn_attempt_route(request: Request, session: SessionDep) -> str:
    """Accept the Learn surface form and record an attempt."""
    raw_form = parse_qs((await request.body()).decode(), keep_blank_values=True)
    form = {key: values[-1] for key, values in raw_form.items()}
    payload = AttemptCreate(
        learner_id=form.get("learner_id", ""),
        prompt_id=form.get("prompt_id", ""),
        response_text=form.get("response_text", ""),
        confidence_rating=_optional_int(form.get("confidence_rating")),
        reference_accessed=form.get("reference_accessed") == "true",
        feedback=StructuredFeedback(
            goal="Record learner attempt",
            observed_evidence=form.get("response_text", ""),
            next_action="Review feedback and continue practice.",
        ),
    )
    attempt = create_attempt(session, **payload.model_dump())
    session.commit()
    session.refresh(attempt)

    return _page(
        "Learn",
        f"""
        <main class="surface learn-surface">
          <header>
            <p class="eyebrow">Attempt recorded</p>
            <h1>Learn</h1>
          </header>
          <section aria-labelledby="feedback-heading">
            <h2 id="feedback-heading">Feedback and next action</h2>
            <p>Attempt <strong>{escape(attempt.id)}</strong> was recorded.</p>
            <p>Review feedback and continue practice.</p>
          </section>
        </main>
        """,
    )


@router.get("/review", response_class=HTMLResponse)
def review_surface_route(
    session: SessionDep,
    learner_id: Annotated[str, Query(min_length=1, max_length=36)] = "learner-1",
    daily_cap: Annotated[int, Query(ge=1, le=100)] = DEFAULT_DAILY_CAP,
) -> str:
    """Return a mobile-friendly Review surface with scheduler reason codes."""
    overview = get_review_queue_overview(
        session,
        learner_id=learner_id,
        settings=SchedulerSettings(daily_cap=daily_cap),
    )
    items = [
        (
            "<li class='queue-item'>"
            f"<strong>{escape(item.reason_code)}</strong>"
            f"<span>{escape(item.reason_explanation)}</span>"
            f"<small>node {escape(item.knowledge_node_id)}; priority {item.priority:.2f}</small>"
            "</li>"
        )
        for item in overview.items
    ]
    if not items:
        items.append("<li class='queue-item empty'>No due review items.</li>")

    return _page(
        "Review",
        f"""
        <main class="surface review-surface">
          <header>
            <p class="eyebrow">Due review queue</p>
            <h1>Review</h1>
          </header>
          <section class="queue-summary" aria-label="Review queue summary">
            <p>Daily cap: <strong>{overview.daily_cap}</strong></p>
            <p>Returned: <strong>{len(overview.items)}</strong></p>
            <p>Backlog: <strong>{overview.backlog_total}</strong></p>
            <p>{escape(overview.backlog_note)}</p>
          </section>
          <section aria-labelledby="queue-heading">
            <h2 id="queue-heading">Reason codes</h2>
            <ul class="review-queue">{''.join(items)}</ul>
          </section>
          <section aria-labelledby="controls-heading">
            <h2 id="controls-heading">Review controls</h2>
            <button type="button" data-action="pause-review">Pause review</button>
            <button type="button" data-action="mark-stale">Mark stale</button>
            <button type="button" data-action="resume-review">Resume</button>
          </section>
        </main>
        """,
    )


def _page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>LMS {escape(title)}</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 0; color: #17202a; background: #f7f8fb; }}
    .surface {{ max-width: 760px; margin: 0 auto; padding: 1rem; }}
    .eyebrow {{ font-size: .8rem; text-transform: uppercase; color: #52606d; }}
    h1 {{ font-size: 1.8rem; margin: .2rem 0 1rem; }}
    h2 {{ font-size: 1rem; margin-top: 1.25rem; }}
    form, section {{ display: grid; gap: .7rem; }}
    textarea, select, button {{ font: inherit; min-height: 2.75rem; }}
    textarea, select {{ width: 100%; box-sizing: border-box; }}
    button {{ border: 1px solid #1f6feb; background: #1f6feb; color: white; padding: .65rem .9rem; }}
    .check {{ display: flex; gap: .5rem; align-items: center; }}
    .source-panel li, .queue-item {{ margin: .45rem 0; overflow-wrap: anywhere; }}
    .queue-item span, .queue-item small {{ display: block; }}
    @media (max-width: 520px) {{ .surface {{ padding: .75rem; }} h1 {{ font-size: 1.45rem; }} }}
  </style>
</head>
<body>
{body}
</body>
</html>"""


def _prompt_body(prompt: Prompt) -> str:
    if not prompt.versions:
        return "Prompt wording unavailable."
    return prompt.versions[-1].body


def _source_citation_items(prompt: Prompt) -> list[str]:
    items: list[str] = []
    for source in prompt.source_references:
        if source.source_visibility == "local-only":
            citation = (
                f"{escape(source.id)}: local-only source hidden; "
                f"{escape(source.hash_algorithm)}={escape(source.content_hash)}"
            )
        else:
            citation = f"{escape(source.id)}: {escape(source.stable_locator)}"
        items.append(f"<li>{citation}</li>")
    return items


def _optional_int(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    return int(value)
