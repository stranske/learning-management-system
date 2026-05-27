"""Learner activity attempt flow surface (Surface 1 attempt loop).

The legacy ``/learn`` route in :mod:`lms.ui.api` is a debug-friendly single
form. This surface is the real activity flow: it presents the prompt with its
demand metadata, collects a response with confidence and reference tracking,
records the attempt, and routes the learner to scored feedback with the next
review hint.
"""

from __future__ import annotations

from html import escape
from typing import Annotated
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from lms.db.session import get_session
from lms.evidence.models import Attempt
from lms.evidence.repository import create_attempt
from lms.evidence.schemas import AttemptCreate, StructuredFeedback
from lms.feedback.models import RubricScore
from lms.feedback.repository import list_feedback_actions, list_feedback_records
from lms.prompts.models import Prompt
from lms.scheduling.service import (
    DEFAULT_DAILY_CAP,
    SchedulerSettings,
    get_review_queue_overview,
)
from lms.ui.shell import empty_state, render_page

router = APIRouter(tags=["learner-ui"])
SessionDep = Annotated[Session, Depends(get_session)]

ATTEMPTS_PATH = "/app/learner/attempts"
FEEDBACK_PATH = "/app/learner/attempts/feedback"


@router.get(ATTEMPTS_PATH, response_class=HTMLResponse)
def attempt_flow_route(
    session: SessionDep,
    learner_id: Annotated[str, Query(min_length=1, max_length=36)] = "learner-1",
    prompt_id: Annotated[str | None, Query(min_length=1, max_length=36)] = None,
) -> str:
    """Return the activity attempt start page for a prompt."""
    return _attempt_start_surface(
        session=session, learner_id=learner_id, prompt_id=prompt_id, error=None
    )


@router.post(ATTEMPTS_PATH, response_class=HTMLResponse)
async def submit_attempt_route(request: Request, session: SessionDep) -> str:
    """Record an attempt and route the learner to scored feedback."""
    form = _read_form((await request.body()).decode())
    learner_id = form.get("learner_id", "")
    prompt_id = form.get("prompt_id", "")
    try:
        payload = AttemptCreate(
            learner_id=learner_id,
            prompt_id=prompt_id,
            response_text=form.get("response_text", ""),
            confidence_rating=_optional_int(form.get("confidence_rating")),
            reference_accessed=form.get("reference_accessed") == "true",
            elapsed_seconds=_optional_int(form.get("elapsed_seconds")),
            feedback=StructuredFeedback(
                goal="Record learner attempt",
                observed_evidence=form.get("response_text", "") or "(no response captured)",
                next_action="Review feedback and continue practice.",
            ),
        )
    except ValidationError:
        return _attempt_start_surface(
            session=session,
            learner_id=learner_id or "learner-1",
            prompt_id=prompt_id or None,
            error="Enter a response and a confidence rating between 1 and 5 before submitting.",
        )

    attempt = create_attempt(session, **payload.model_dump())
    session.commit()
    session.refresh(attempt)
    return _attempt_feedback_surface(
        session=session,
        learner_id=payload.learner_id,
        prompt_id=payload.prompt_id,
        attempt_id=attempt.id,
        just_submitted=True,
    )


@router.get(FEEDBACK_PATH, response_class=HTMLResponse)
def attempt_feedback_route(
    session: SessionDep,
    learner_id: Annotated[str, Query(min_length=1, max_length=36)] = "learner-1",
    prompt_id: Annotated[str | None, Query(min_length=1, max_length=36)] = None,
    attempt_id: Annotated[str | None, Query(min_length=1, max_length=36)] = None,
) -> str:
    """Return scored feedback for the latest (or named) attempt."""
    return _attempt_feedback_surface(
        session=session,
        learner_id=learner_id,
        prompt_id=prompt_id,
        attempt_id=attempt_id,
        just_submitted=False,
    )


def _attempt_start_surface(
    *,
    session: Session,
    learner_id: str,
    prompt_id: str | None,
    error: str | None,
) -> str:
    prompt = session.get(Prompt, prompt_id) if prompt_id else None

    if prompt is None:
        return _start_page(
            learner_id=learner_id,
            body=empty_state(
                "No prompt selected",
                "Open this activity from an assigned task or pass a published prompt id "
                "to begin an attempt.",
            ),
        )

    if prompt.status != "published":
        return _start_page(
            learner_id=learner_id,
            body=empty_state(
                "Prompt not available",
                f"This prompt is {escape(prompt.status)} and cannot be attempted until it is "
                "published. Ask the author to publish it before practising.",
            ),
        )

    latest = _latest_attempt(session, learner_id=learner_id, prompt_id=prompt.id)
    already_submitted = (
        ""
        if latest is None
        else f"""
          <section class="notice" aria-labelledby="resubmit-heading">
            <h2 id="resubmit-heading">You already submitted an attempt for this prompt</h2>
            <p>Your most recent confidence was {escape(_confidence_label(latest.confidence_rating))}.</p>
            <p><a href="{FEEDBACK_PATH}?learner_id={escape(learner_id)}&prompt_id={escape(prompt.id)}">
              View your feedback and next action</a>, or submit another attempt below.</p>
          </section>
        """
    )

    return _start_page(
        learner_id=learner_id,
        body=f"""
        {_error_notice(error)}
        {already_submitted}
        <section aria-labelledby="task-heading">
          <h2 id="task-heading">Your task</h2>
          <p class="prompt-text">{escape(_prompt_body(prompt))}</p>
          <ul class="prompt-meta">
            <li>Demand level: <strong>{escape(prompt.demand_level)}</strong></li>
            <li>Expected answer form: <strong>{escape(prompt.expected_answer_form)}</strong></li>
            <li>Cognitive action: <strong>{escape(prompt.intended_cognitive_action)}</strong></li>
          </ul>
          <p class="prompt-provenance">{escape(_prompt_provenance(prompt))}</p>
        </section>
        <form class="attempt-form" method="post" action="{ATTEMPTS_PATH}" data-started-at="">
          <input type="hidden" name="learner_id" value="{escape(learner_id)}">
          <input type="hidden" name="prompt_id" value="{escape(prompt.id)}">
          <input type="hidden" id="elapsed_seconds" name="elapsed_seconds" value="">
          <label for="response_text">Your response</label>
          <textarea id="response_text" name="response_text" rows="6" required></textarea>
          <label for="confidence_rating">Confidence</label>
          <select id="confidence_rating" name="confidence_rating">
            <option value="1">1 - unsure</option>
            <option value="2">2</option>
            <option value="3" selected>3</option>
            <option value="4">4</option>
            <option value="5">5 - confident</option>
          </select>
          <label class="check">
            <input type="checkbox" name="reference_accessed" value="true">
            I opened a reference during this attempt
          </label>
          <button type="submit">Submit attempt</button>
        </form>
        <section aria-labelledby="sources-heading" class="source-panel">
          <h2 id="sources-heading">Source citations after attempt</h2>
          <ul>{_citation_list(prompt)}</ul>
        </section>
        <script>
          (function () {{
            var form = document.querySelector(".attempt-form");
            if (!form) {{ return; }}
            var startedAt = Date.now();
            form.addEventListener("submit", function () {{
              var field = form.querySelector("#elapsed_seconds");
              if (field && !field.value) {{
                field.value = Math.round((Date.now() - startedAt) / 1000);
              }}
            }});
          }})();
        </script>
        """,
    )


def _attempt_feedback_surface(
    *,
    session: Session,
    learner_id: str,
    prompt_id: str | None,
    attempt_id: str | None,
    just_submitted: bool,
) -> str:
    attempt = _resolve_attempt(
        session, learner_id=learner_id, prompt_id=prompt_id, attempt_id=attempt_id
    )
    if attempt is None:
        return _feedback_page(
            learner_id=learner_id,
            body=empty_state(
                "No attempt yet",
                "Submit an attempt to see scored feedback and your next action.",
            ),
        )

    prompt = session.get(Prompt, attempt.prompt_id)
    eyebrow = "Attempt recorded" if just_submitted else "Scored feedback"

    return _feedback_page(
        learner_id=learner_id,
        eyebrow=eyebrow,
        body=f"""
        <section aria-labelledby="attempt-heading">
          <h2 id="attempt-heading">Your attempt</h2>
          <p class="attempt-response">{escape(attempt.response_text)}</p>
          <ul class="attempt-meta">
            <li>Confidence: <strong>{escape(_confidence_label(attempt.confidence_rating))}</strong></li>
            <li>Reference accessed: <strong>{"yes" if attempt.reference_accessed else "no"}</strong></li>
            <li>Elapsed: <strong>{_elapsed_label(attempt.elapsed_seconds)}</strong></li>
          </ul>
        </section>
        <section aria-labelledby="score-heading">
          <h2 id="score-heading">Scored feedback</h2>
          {_score_block(session, attempt)}
          {_feedback_records_block(session, attempt)}
        </section>
        <section aria-labelledby="next-action-heading">
          <h2 id="next-action-heading">Next action</h2>
          {_feedback_actions_block(session, attempt)}
        </section>
        <section aria-labelledby="next-review-heading">
          <h2 id="next-review-heading">Next review</h2>
          {_next_review_block(session, learner_id=learner_id)}
        </section>
        <section aria-labelledby="sources-heading" class="source-panel">
          <h2 id="sources-heading">Source citations after attempt</h2>
          <ul>{_citation_list(prompt) if prompt is not None else "<li>No source citations linked.</li>"}</ul>
        </section>
        """,
    )


def _score_block(session: Session, attempt: Attempt) -> str:
    score = session.scalars(
        select(RubricScore)
        .where(RubricScore.attempt_id == attempt.id)
        .order_by(RubricScore.created_at.desc())
        .limit(1)
    ).first()
    if score is not None:
        return (
            "<p class='score'>Rubric score "
            f"<strong>{score.raw_score:g}/{score.max_score:g}</strong> "
            f"({score.normalized_score:.0%}); correctness "
            f"{_correctness_label(score.normalized_score >= 0.85)}.</p>"
        )

    correctness = _attempt_correctness(attempt)
    if correctness is None:
        return (
            "<p class='score'>Awaiting scoring. Feedback appears once this attempt is scored.</p>"
        )
    return f"<p class='score'>Correctness: {_correctness_label(correctness)}.</p>"


def _feedback_records_block(session: Session, attempt: Attempt) -> str:
    records = list_feedback_records(session, attempt_id=attempt.id)
    if not records:
        return ""
    items = []
    for record in records:
        gap = f"<span class='gap'>Gap: {escape(record.gap)}</span>" if record.gap else ""
        diagnosis = (
            f"<span class='diagnosis'>{escape(record.diagnosis)}</span>" if record.diagnosis else ""
        )
        items.append(
            "<li>"
            f"<strong>{escape(record.goal)}</strong>"
            f"<span>{escape(record.observed_evidence)}</span>"
            f"{diagnosis}{gap}"
            "</li>"
        )
    return f"<ul class='feedback-records'>{''.join(items)}</ul>"


def _feedback_actions_block(session: Session, attempt: Attempt) -> str:
    actions = list_feedback_actions(session, attempt_id=attempt.id)
    if not actions:
        return empty_state(
            "No follow-up required",
            "This attempt did not trigger a remediation or revision action.",
        )
    items = [
        (
            "<li class='feedback-action'>"
            f"<strong>{escape(action.title)}</strong>"
            f"<span>{escape(action.action_type)}</span>"
            f"{('<p>' + escape(action.instructions) + '</p>') if action.instructions else ''}"
            "</li>"
        )
        for action in actions
    ]
    return f"<ul class='feedback-actions'>{''.join(items)}</ul>"


def _next_review_block(session: Session, *, learner_id: str) -> str:
    overview = get_review_queue_overview(
        session,
        learner_id=learner_id,
        settings=SchedulerSettings(daily_cap=DEFAULT_DAILY_CAP),
    )
    if not overview.items:
        return f"<p class='next-review empty'>{escape(overview.backlog_note)}</p>"
    item = overview.items[0]
    return (
        "<p class='next-review'>"
        f"<strong>{escape(item.reason_code)}</strong>: {escape(item.reason_explanation)} "
        f"(due {escape(item.due_at.date().isoformat())}; node {escape(item.knowledge_node_id)})."
        "</p>"
    )


def _resolve_attempt(
    session: Session,
    *,
    learner_id: str,
    prompt_id: str | None,
    attempt_id: str | None,
) -> Attempt | None:
    if attempt_id is not None:
        return session.get(Attempt, attempt_id)
    return _latest_attempt(session, learner_id=learner_id, prompt_id=prompt_id)


def _latest_attempt(session: Session, *, learner_id: str, prompt_id: str | None) -> Attempt | None:
    statement = select(Attempt).where(Attempt.learner_id == learner_id)
    if prompt_id is not None:
        statement = statement.where(Attempt.prompt_id == prompt_id)
    statement = statement.order_by(Attempt.created_at.desc()).limit(1)
    return session.scalars(statement).first()


def _attempt_correctness(attempt: Attempt) -> bool | None:
    for record in attempt.evidence_records:
        if record.correctness is not None:
            return record.correctness
    return None


def _start_page(*, learner_id: str, body: str) -> str:
    return render_page(
        "Attempt",
        f"""
        <main class="surface attempt-surface">
          <header>
            <p class="eyebrow">Activity attempt</p>
            <h1>Attempt</h1>
          </header>
          {body}
        </main>
        """,
        active_path="/app/learner",
    )


def _feedback_page(*, learner_id: str, body: str, eyebrow: str = "Scored feedback") -> str:
    return render_page(
        "Feedback",
        f"""
        <main class="surface feedback-surface">
          <header>
            <p class="eyebrow">{escape(eyebrow)}</p>
            <h1>Feedback</h1>
          </header>
          {body}
        </main>
        """,
        active_path="/app/learner",
    )


def _error_notice(error: str | None) -> str:
    if not error:
        return ""
    return f"<p role='alert' class='validation-error'>{escape(error)}</p>"


def _citation_list(prompt: Prompt | None) -> str:
    if prompt is None:
        return "<li>No source citations linked.</li>"
    items = []
    for source in prompt.source_references:
        if source.source_visibility == "local-only":
            citation = (
                f"{escape(source.id)}: local-only source hidden; "
                f"{escape(source.hash_algorithm)}={escape(source.content_hash)}"
            )
        else:
            citation = f"{escape(source.id)}: {escape(source.stable_locator)}"
        items.append(f"<li>{citation}</li>")
    return "".join(items) if items else "<li>No source citations linked.</li>"


def _prompt_body(prompt: Prompt) -> str:
    if not prompt.versions:
        return "Prompt wording unavailable."
    return prompt.versions[-1].body


def _prompt_provenance(prompt: Prompt) -> str:
    return (
        f"Provenance: {prompt.authoring_method}; "
        f"author {prompt.authoring_actor}; reviewer {prompt.reviewing_actor}."
    )


def _confidence_label(value: int | None) -> str:
    return "not recorded" if value is None else f"{value}/5"


def _correctness_label(correct: bool) -> str:
    return "correct" if correct else "incorrect"


def _elapsed_label(value: int | None) -> str:
    return "not recorded" if value is None else f"{value}s"


def _read_form(body: str) -> dict[str, str]:
    raw_form = parse_qs(body, keep_blank_values=True)
    return {key: values[-1] for key, values in raw_form.items()}


def _optional_int(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except ValueError:
        return None
