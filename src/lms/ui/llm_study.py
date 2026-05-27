"""Learner-facing LLM study session surface (development-testing Surface 2).

This surface lets a learner start a formative ``study-coach`` or ``practice``
turn and inspect what the LLM backend returns: session mode, coaching
intensity, trace class, model identity, cost summary, policy decision, source
flags, and the keep/forget trace control. It reuses the ``lms.llm.api`` route
handlers as the service layer so provider routing, budgets, and source-citation
policy stay defined in one place.
"""

from __future__ import annotations

from html import escape
from typing import Annotated
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from lms.db.session import get_session
from lms.llm.api import (
    LLMSessionCreate,
    LLMSessionRead,
    LLMTraceControlRead,
    LLMTraceControlRequest,
    control_llm_trace_route,
    create_llm_session_route,
)
from lms.llm.exceptions import BudgetExceeded
from lms.ui.shell import empty_state, render_page

router = APIRouter(tags=["learner-ui"])
SessionDep = Annotated[Session, Depends(get_session)]

_DEFAULT_LEARNER = "learner-1"
_MODE_CHOICES = ("study-coach", "practice")
_INTENSITY_CHOICES = ("full", "light", "quiet")


@router.get("/app/learner/llm-study", response_class=HTMLResponse)
def llm_study_route(
    learner_id: Annotated[str, Query(min_length=1, max_length=36)] = _DEFAULT_LEARNER,
) -> str:
    """Return the LLM study surface with a fresh start form."""
    return _study_surface(learner_id=learner_id, result_html="")


@router.post("/app/learner/llm-study/sessions", response_class=HTMLResponse)
async def create_llm_study_session_route(request: Request, session: SessionDep) -> str:
    """Start one formative study/practice turn and render the result."""
    form = await _read_form(request)
    learner_id = form.get("learner_id") or _DEFAULT_LEARNER
    try:
        payload = LLMSessionCreate(
            learner_id=learner_id,
            mode=form.get("mode", "study-coach"),  # type: ignore[arg-type]
            user_message=form.get("user_message", ""),
            coaching_intensity=form.get("coaching_intensity", "full"),  # type: ignore[arg-type]
            source_constraints=_split_csv(form.get("source_constraints", "")),
            assessment_restricted=form.get("assessment_restricted") == "true",
            retrieval_active=form.get("retrieval_active") == "true",
        )
    except ValidationError:
        return _study_surface(
            learner_id=learner_id,
            result_html="",
            error="Enter a message and a supported mode to start a study turn.",
        )
    try:
        read = create_llm_session_route(payload, session)
    except BudgetExceeded:
        return _study_surface(
            learner_id=learner_id,
            result_html=empty_state(
                "Budget kill-switch stopped this turn",
                "The daily LLM budget was exhausted, so the turn was stopped before any "
                "provider call. No trace was created.",
            ),
            error="The daily LLM budget kill-switch stopped this turn.",
        )
    return _study_surface(
        learner_id=learner_id,
        result_html=_session_result(read, learner_id=learner_id),
    )


@router.post(
    "/app/learner/llm-study/sessions/{session_id}/trace-control",
    response_class=HTMLResponse,
)
async def control_llm_study_trace_route(
    session_id: str, request: Request, session: SessionDep
) -> str:
    """Apply a learner keep/forget control and render the updated trace state."""
    form = await _read_form(request)
    learner_id = form.get("learner_id") or _DEFAULT_LEARNER
    try:
        payload = LLMTraceControlRequest(
            action=form.get("action", ""),  # type: ignore[arg-type]
            actor_id=learner_id,
        )
    except ValidationError:
        return _study_surface(
            learner_id=learner_id,
            result_html="",
            error="Choose keep or forget for this trace.",
        )
    try:
        read = control_llm_trace_route(session_id, payload, session)
    except HTTPException as exc:
        return _study_surface(
            learner_id=learner_id,
            result_html="",
            error=str(exc.detail),
        )
    return _study_surface(
        learner_id=learner_id,
        result_html=_trace_control_result(read),
    )


def _study_surface(*, learner_id: str, result_html: str, error: str | None = None) -> str:
    body = f"""
        <main class="surface llm-study-surface">
          {_notice(error)}
          <header>
            <p class="eyebrow">Guided LLM study</p>
            <h1>LLM study session</h1>
            <p>Start a formative study-coach or practice turn. Provider routing and
            budgets are fixed by policy; this surface only shows what the backend
            returns.</p>
          </header>
          {_start_form(learner_id)}
          {_trace_handling_note()}
          <section aria-labelledby="result-heading" class="study-result">
            <h2 id="result-heading">Session result</h2>
            {
        result_html
        or empty_state(
            "No session yet",
            "Start a study turn above to see the response, trace class, cost, "
            "model identity, and keep/forget controls.",
        )
    }
          </section>
        </main>
    """
    return render_page("LLM study", body, active_path="/app/learner")


def _start_form(learner_id: str) -> str:
    return f"""
          <form method="post" action="/app/learner/llm-study/sessions" class="llm-study-form">
            <input type="hidden" name="learner_id" value="{escape(learner_id)}">
            {_select("mode", _MODE_CHOICES, "study-coach")}
            {_select("coaching_intensity", _INTENSITY_CHOICES, "full")}
            <label for="user_message">Your message</label>
            <textarea id="user_message" name="user_message" rows="4" required></textarea>
            <label for="source_constraints">Required source ids (comma separated)</label>
            <input id="source_constraints" name="source_constraints"
              aria-describedby="source-hint">
            <small id="source-hint">Responses that omit a required source id are flagged
            <code>unverified</code>.</small>
            <label class="check">
              <input type="checkbox" name="assessment_restricted" value="true">
              Assessment-restricted (disable hints and direct feedback)
            </label>
            <label class="check">
              <input type="checkbox" name="retrieval_active" value="true">
              Retrieval practice active
            </label>
            <button type="submit">Start study turn</button>
          </form>
          <p class="note">Transfer-mode interactions are read-only and are not started
          from this surface.</p>
    """


def _trace_handling_note() -> str:
    return """
          <section aria-labelledby="trace-handling-heading" class="trace-handling">
            <h2 id="trace-handling-heading">Trace handling</h2>
            <ul>
              <li><strong>formative</strong> traces keep a short local summary for your
              own review and are not exported verbatim to external trace tooling.</li>
              <li><strong>ephemeral</strong> traces are held locally only, are never
              externally exported, and cannot be kept for verbatim retention.</li>
            </ul>
            <p>Verbatim transcript bodies are never exported from this surface; only the
            current response and trace metadata are shown.</p>
          </section>
    """


def _session_result(read: LLMSessionRead, *, learner_id: str) -> str:
    policy = read.policy_decision
    cost = read.cost_summary
    return f"""
          <article class="session-card" aria-label="LLM session result">
            <dl class="session-meta">
              <dt>Session id</dt><dd>{escape(read.session_id)}</dd>
              <dt>Mode</dt><dd>{escape(read.mode)}</dd>
              <dt>Coaching intensity</dt><dd>{escape(read.coaching_intensity)}</dd>
              <dt>Trace class</dt><dd>{escape(read.trace_class)}</dd>
              <dt>Model</dt><dd>{escape(read.model)}</dd>
              <dt>Cost</dt><dd>{read.cost_micro_usd} micro-USD
                (input {int(cost.get("input_tokens", 0))} tokens,
                output {int(cost.get("output_tokens", 0))} tokens)</dd>
              <dt>Trace control state</dt><dd>{escape(read.trace_control_state)}</dd>
              <dt>External export allowed</dt>
              <dd>{_yes_no(read.external_export_allowed)}</dd>
            </dl>
            {_flags_block(read.flags)}
            <section aria-labelledby="response-heading">
              <h3 id="response-heading">Response</h3>
              <p class="response-text">{escape(read.response_text)}</p>
            </section>
            <section aria-labelledby="policy-heading">
              <h3 id="policy-heading">Policy decision</h3>
              <ul>
                <li>Behavior: {escape(str(policy.get("behavior", "")))}</li>
                <li>Learning risk: {escape(str(policy.get("learning_risk", "")))}</li>
                <li>Next action: {escape(str(policy.get("next_action", "")))}</li>
                <li>Response style: {escape(str(policy.get("response_style", "")))}</li>
                <li>Direct answer allowed:
                  {_yes_no(bool(policy.get("direct_answer_allowed")))}</li>
              </ul>
            </section>
            {
        _trace_control_form(
            session_id=read.session_id,
            learner_id=learner_id,
            trace_class=read.trace_class,
        )
    }
          </article>
    """


def _trace_control_form(*, session_id: str, learner_id: str, trace_class: str) -> str:
    keep_attr = " disabled" if trace_class == "ephemeral" else ""
    keep_note = (
        "<small>Ephemeral traces cannot be kept for verbatim retention.</small>"
        if trace_class == "ephemeral"
        else ""
    )
    action = f"/app/learner/llm-study/sessions/{escape(session_id)}/trace-control"
    return f"""
            <section aria-labelledby="trace-control-heading" class="trace-control">
              <h3 id="trace-control-heading">Keep or forget this trace</h3>
              <form method="post" action="{action}">
                <input type="hidden" name="learner_id" value="{escape(learner_id)}">
                <button type="submit" name="action" value="keep"{keep_attr}>Keep</button>
                <button type="submit" name="action" value="forget">Forget</button>
              </form>
              {keep_note}
            </section>
    """


def _trace_control_result(read: LLMTraceControlRead) -> str:
    forgotten = read.trace_control_state == "forgotten"
    headline = "Trace forgotten." if forgotten else f"Trace state: {read.trace_control_state}."
    return f"""
          <article class="trace-control-result" aria-label="Trace control result">
            <p class="success">{escape(headline)}</p>
            <dl>
              <dt>Session id</dt><dd>{escape(read.session_id)}</dd>
              <dt>Trace class</dt><dd>{escape(read.trace_class)}</dd>
              <dt>Trace control state</dt><dd>{escape(read.trace_control_state)}</dd>
              <dt>Retained response summary</dt>
              <dd>{_yes_no(read.response_summary_retained)}</dd>
              <dt>External export allowed</dt>
              <dd>{_yes_no(read.external_export_allowed)}</dd>
            </dl>
          </article>
    """


def _flags_block(flags: list[str]) -> str:
    if not flags:
        return '<p class="flags none">No flags on this turn.</p>'
    items = "".join(f'<li class="flag flag-{escape(flag)}">{escape(flag)}</li>' for flag in flags)
    return (
        '<section aria-label="Response flags"><h3>Flags</h3>'
        f'<ul class="flags">{items}</ul></section>'
    )


def _select(name: str, choices: tuple[str, ...], selected: str) -> str:
    label = name.replace("_", " ")
    options = "".join(
        f'<option value="{escape(choice)}"'
        f"{' selected' if choice == selected else ''}>{escape(choice)}</option>"
        for choice in choices
    )
    return (
        f'<label for="{escape(name)}">{escape(label)}</label>'
        f'<select id="{escape(name)}" name="{escape(name)}">{options}</select>'
    )


def _notice(error: str | None) -> str:
    if error is not None:
        return f"<p role='alert' class='validation-error'>{escape(error)}</p>"
    return ""


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


async def _read_form(request: Request) -> dict[str, str]:
    raw_form = parse_qs((await request.body()).decode(), keep_blank_values=True)
    return {key: values[-1] for key, values in raw_form.items()}
