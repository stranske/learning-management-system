"""Learner-facing feedback, hint, model-answer, and revision HTML surfaces."""

from __future__ import annotations

from collections.abc import Sequence
from html import escape
from typing import Annotated
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from lms.db.session import get_session
from lms.feedback.models import (
    FeedbackAction,
    FeedbackRecord,
    Hint,
    ModelAnswer,
    RevisionRequest,
    RubricScore,
)
from lms.feedback.repository import (
    create_revision_request,
    get_feedback_record,
    get_hint,
    get_model_answer,
    list_feedback_actions,
    list_feedback_records,
    list_hints,
    list_model_answers,
    list_revision_requests,
    list_rubric_scores,
    reveal_hint,
    reveal_model_answer,
    submit_revision_request,
)
from lms.ui.shell import empty_state, render_page

router = APIRouter(tags=["learner-feedback-ui"])
SessionDep = Annotated[Session, Depends(get_session)]


@router.get("/app/learner/feedback", response_class=HTMLResponse)
def learner_feedback_list_route(
    session: SessionDep,
    learner_id: Annotated[str, Query(min_length=1, max_length=36)] = "learner-1",
) -> str:
    """Return feedback records for a learner."""
    records = list_feedback_records(session, learner_id=learner_id)
    if not records:
        body = empty_state(
            "No feedback yet",
            "Feedback appears here after an attempt is scored or an author opens a next action.",
        )
    else:
        body = (
            '<section aria-labelledby="feedback-list-heading">'
            '<h2 id="feedback-list-heading">Feedback records</h2>'
            '<ul class="panel-list">'
            + "".join(_record_list_item(record) for record in records)
            + "</ul></section>"
        )
    return render_page(
        "Feedback",
        f"""
        <main class="surface feedback-surface">
          <header>
            <p class="eyebrow">Learner feedback</p>
            <h1>Feedback</h1>
          </header>
          {body}
        </main>
        """,
        active_path="/app/learner",
    )


@router.get("/app/learner/feedback/{feedback_record_id}", response_class=HTMLResponse)
def learner_feedback_detail_route(feedback_record_id: str, session: SessionDep) -> str:
    """Return one learner feedback detail page."""
    record = get_feedback_record(session, feedback_record_id)
    if record is None:
        return _missing_feedback_page()
    return _feedback_detail_page(session, record)


@router.post("/app/learner/feedback/{feedback_record_id}/hints/{hint_id}/reveal")
def learner_hint_reveal_route(
    feedback_record_id: str,
    hint_id: str,
    session: SessionDep,
) -> HTMLResponse:
    """Reveal a hint from the feedback detail page."""
    record = get_feedback_record(session, feedback_record_id)
    hint = get_hint(session, hint_id)
    if record is None or hint is None:
        return HTMLResponse(_missing_feedback_page(), status_code=404)
    try:
        reveal_hint(
            session,
            hint,
            learner_id=record.learner_id,
            attempt_id=record.attempt_id,
        )
        session.commit()
    except ValueError as exc:
        session.rollback()
        return HTMLResponse(_feedback_detail_page(session, record, error=str(exc)), status_code=422)
    return HTMLResponse(
        _feedback_detail_page(session, record, message=f"Hint revealed: {hint.hint_text}")
    )


@router.post("/app/learner/feedback/{feedback_record_id}/model-answers/{model_answer_id}/reveal")
def learner_model_answer_reveal_route(
    feedback_record_id: str,
    model_answer_id: str,
    session: SessionDep,
) -> HTMLResponse:
    """Reveal a model answer after backend policy allows it."""
    record = get_feedback_record(session, feedback_record_id)
    answer = get_model_answer(session, model_answer_id)
    if record is None or answer is None:
        return HTMLResponse(_missing_feedback_page(), status_code=404)
    try:
        reveal_model_answer(
            session,
            answer,
            learner_id=record.learner_id,
            attempt_id=record.attempt_id,
        )
        session.commit()
    except ValueError as exc:
        session.rollback()
        return HTMLResponse(_feedback_detail_page(session, record, error=str(exc)), status_code=422)
    return HTMLResponse(
        _feedback_detail_page(
            session,
            record,
            message=f"Model answer revealed: {reveal_model_answer_text(answer.answer_body)}",
        )
    )


@router.post("/app/learner/feedback/{feedback_record_id}/revision")
async def learner_revision_submit_route(
    feedback_record_id: str,
    request: Request,
    session: SessionDep,
) -> HTMLResponse:
    """Open or reuse a revision request and submit the learner revision."""
    record = get_feedback_record(session, feedback_record_id)
    if record is None:
        return HTMLResponse(_missing_feedback_page(), status_code=404)
    form = await _read_form(request)
    response_text = form.get("response_text", "").strip()
    if not response_text:
        return HTMLResponse(
            _feedback_detail_page(session, record, error="Revision response is required."),
            status_code=422,
        )
    try:
        revision = _open_revision_request(session, record)
        submit_revision_request(
            session,
            revision,
            response_text=response_text,
            confidence_rating=_optional_int(form.get("confidence_rating")),
        )
        session.commit()
        session.refresh(revision)
    except ValueError as exc:
        session.rollback()
        return HTMLResponse(_feedback_detail_page(session, record, error=str(exc)), status_code=422)
    return HTMLResponse(
        _feedback_detail_page(
            session,
            record,
            message=f"Revision submitted. Status: {revision.status}.",
        )
    )


def _feedback_detail_page(
    session: Session,
    record: FeedbackRecord,
    *,
    message: str | None = None,
    error: str | None = None,
) -> str:
    actions = list_feedback_actions(
        session,
        feedback_record_id=record.id,
        learner_id=record.learner_id,
    )
    rubric_scores = list_rubric_scores(
        session,
        attempt_id=record.attempt_id,
        learner_id=record.learner_id,
    )
    revisions = list_revision_requests(session, feedback_record_id=record.id)
    hints = list_hints(session, prompt_id=record.prompt_id) if record.prompt_id else []
    model_answers = (
        list_model_answers(session, prompt_id=record.prompt_id) if record.prompt_id else []
    )

    return render_page(
        "Feedback",
        f"""
        <main class="surface feedback-surface">
          <header>
            <p class="eyebrow">Learner feedback</p>
            <h1>{escape(record.goal)}</h1>
          </header>
          {_notice(message, "notice")}
          {_notice(error, "error")}
          <section aria-labelledby="feedback-summary-heading">
            <h2 id="feedback-summary-heading">What the feedback says</h2>
            <dl>
              <dt>Observed evidence</dt>
              <dd>{escape(record.observed_evidence)}</dd>
              <dt>Diagnosis</dt>
              <dd>{escape(record.diagnosis or "No diagnosis recorded yet.")}</dd>
              <dt>Gap</dt>
              <dd>{escape(record.gap or "No specific gap recorded yet.")}</dd>
            </dl>
          </section>
          {_actions_panel(actions)}
          {_rubric_panel(rubric_scores)}
          {_hint_panel(record, hints)}
          {_model_answer_panel(record, model_answers)}
          {_revision_panel(revisions)}
          {_revision_form(record)}
          <nav aria-label="Feedback navigation">
            <a href="/learn">Attempt flow</a>
            <a href="/app/learner/review">Review queue</a>
            <a href="/app/learner">Learner dashboard</a>
          </nav>
        </main>
        """,
        active_path="/app/learner",
    )


def _record_list_item(record: FeedbackRecord) -> str:
    return (
        '<li class="panel-item">'
        f'<a href="/app/learner/feedback/{escape(record.id)}">{escape(record.goal)}</a>'
        f"<span>{escape(record.gap or record.feedback_level)}</span>"
        "</li>"
    )


def _actions_panel(actions: Sequence[FeedbackAction]) -> str:
    items = []
    for action in actions:
        items.append(
            "<li class='panel-item'>"
            f"<strong>{escape(action.title)}</strong>"
            f"<span>{escape(action.instructions or 'No extra instructions recorded.')}</span>"
            f"<small>{escape(action.action_type)} - {escape(action.status)}</small>"
            "</li>"
        )
    if not items:
        items.append("<li class='panel-item'>No next action recorded yet.</li>")
    return (
        '<section aria-labelledby="feedback-actions-heading">'
        '<h2 id="feedback-actions-heading">Next actions</h2>'
        f'<ul class="panel-list">{"".join(items)}</ul>'
        "</section>"
    )


def _rubric_panel(scores: Sequence[RubricScore]) -> str:
    items = []
    for score in scores:
        for criterion in score.criterion_scores:
            items.append(
                "<li class='panel-item'>"
                f"<strong>{escape(str(criterion.get('description', 'Criterion')))}</strong>"
                f"<span>{escape(str(criterion.get('points', 0)))} / "
                f"{escape(str(criterion.get('max_points', 0)))} points</span>"
                f"<small>{escape(str(criterion.get('rationale') or 'No formative comment.'))}</small>"
                "</li>"
            )
    if not items:
        items.append("<li class='panel-item'>No rubric breakdown recorded yet.</li>")
    return (
        '<section aria-labelledby="rubric-heading">'
        '<h2 id="rubric-heading">Rubric breakdown</h2>'
        f'<ul class="panel-list">{"".join(items)}</ul>'
        "</section>"
    )


def _hint_panel(record: FeedbackRecord, hints: Sequence[Hint]) -> str:
    items = []
    for hint in hints:
        items.append(
            "<li class='panel-item'>"
            f"<strong>Hint {hint.reveal_order}</strong>"
            f"<span>{escape(hint.support_level)}</span>"
            f'<form method="post" action="/app/learner/feedback/{escape(record.id)}/hints/{escape(hint.id)}/reveal">'
            "<button type='submit'>Reveal hint</button>"
            "</form></li>"
        )
    if not items:
        items.append("<li class='panel-item'>No hints are linked to this prompt.</li>")
    return (
        '<section aria-labelledby="hints-heading">'
        '<h2 id="hints-heading">Hints</h2>'
        f'<ul class="panel-list">{"".join(items)}</ul>'
        "</section>"
    )


def _model_answer_panel(record: FeedbackRecord, model_answers: Sequence[ModelAnswer]) -> str:
    items = []
    for answer in model_answers:
        items.append(
            "<li class='panel-item'>"
            f"<strong>Model answer available</strong>"
            f"<span>Reveal policy: {escape(answer.reveal_policy)}</span>"
            f'<form method="post" action="/app/learner/feedback/{escape(record.id)}/model-answers/{escape(answer.id)}/reveal">'
            "<button type='submit'>Reveal model answer</button>"
            "</form></li>"
        )
    if not items:
        items.append("<li class='panel-item'>No model answer is linked to this prompt.</li>")
    return (
        '<section aria-labelledby="model-answer-heading">'
        '<h2 id="model-answer-heading">Model answer</h2>'
        f'<ul class="panel-list">{"".join(items)}</ul>'
        "</section>"
    )


def _revision_panel(revisions: Sequence[RevisionRequest]) -> str:
    items = []
    for revision in revisions:
        items.append(
            "<li class='panel-item'>"
            f"<strong>Revision {escape(revision.status)}</strong>"
            f"<span>Request {escape(revision.id)}</span>"
            f"<small>Revised attempt: {escape(revision.revised_attempt_id or 'not submitted')}</small>"
            "</li>"
        )
    if not items:
        items.append("<li class='panel-item'>No revision request has been submitted yet.</li>")
    return (
        '<section aria-labelledby="revision-state-heading">'
        '<h2 id="revision-state-heading">Revision status</h2>'
        f'<ul class="panel-list">{"".join(items)}</ul>'
        "</section>"
    )


def _revision_form(record: FeedbackRecord) -> str:
    return f"""
    <section aria-labelledby="revision-form-heading">
      <h2 id="revision-form-heading">Submit a revision</h2>
      <form method="post" action="/app/learner/feedback/{escape(record.id)}/revision">
        <label for="response_text">Revised response</label>
        <textarea id="response_text" name="response_text" rows="5"></textarea>
        <label for="confidence_rating">Confidence</label>
        <select id="confidence_rating" name="confidence_rating">
          <option value="">Not recorded</option>
          <option value="1">1 - unsure</option>
          <option value="2">2</option>
          <option value="3">3</option>
          <option value="4">4</option>
          <option value="5">5 - confident</option>
        </select>
        <button type="submit">Submit revision</button>
      </form>
    </section>
    """


def _open_revision_request(session: Session, record: FeedbackRecord) -> RevisionRequest:
    active = list_revision_requests(
        session,
        feedback_record_id=record.id,
        statuses=("open",),
        limit=1,
    )
    if active:
        return active[0]
    return create_revision_request(
        session,
        learner_id=record.learner_id,
        feedback_record_id=record.id,
        prompt_id=record.prompt_id,
        original_attempt_id=record.attempt_id,
    )


async def _read_form(request: Request) -> dict[str, str]:
    raw_form = parse_qs((await request.body()).decode(), keep_blank_values=True)
    return {key: values[-1] for key, values in raw_form.items()}


def _optional_int(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _notice(text: str | None, class_name: str) -> str:
    if text is None:
        return ""
    return f'<p class="{escape(class_name)}">{escape(text)}</p>'


def reveal_model_answer_text(answer_body: str) -> str:
    """Return model answer text through a small helper for explicit reveal points."""
    return answer_body


def _missing_feedback_page() -> str:
    return render_page(
        "Feedback",
        """
        <main class="surface feedback-surface">
          <header>
            <p class="eyebrow">Learner feedback</p>
            <h1>Feedback not found</h1>
          </header>
        </main>
        """,
        active_path="/app/learner",
    )
