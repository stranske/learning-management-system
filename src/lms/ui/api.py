"""Minimal HTML surfaces for testing the learner loop."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from html import escape
from importlib.resources import files
from json import JSONDecodeError, loads
from typing import Annotated, Any
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from lms.capability.models import CapabilityTarget, MaintenancePlan
from lms.capability.repository import list_capability_targets, list_maintenance_plans
from lms.cases.repository import add_decision_point, create_case, get_case, list_cases
from lms.db.session import get_session
from lms.evidence.models import Attempt, EvidenceRecord
from lms.evidence.repository import create_attempt
from lms.evidence.schemas import AttemptCreate, StructuredFeedback
from lms.feedback.models import FeedbackAction
from lms.feedback.repository import (
    create_feedback_template,
    create_rubric,
    get_feedback_template,
    list_feedback_actions,
    list_feedback_templates,
    list_rubrics,
    render_feedback_template,
)
from lms.graphs.models import (
    EDGE_STATUSES,
    EDGE_TYPES,
    KNOWLEDGE_TYPES,
    NODE_STATUSES,
    KnowledgeNode,
)
from lms.graphs.repository import (
    create_knowledge_edge,
    create_knowledge_node,
    list_knowledge_edges,
    list_knowledge_nodes,
)
from lms.learners.models import GOAL_STATUSES, LearningGoal
from lms.learners.repository import create_learning_goal, list_learning_goals_for_learner
from lms.mastery.service import mastery_estimates_for_learner
from lms.prompts.models import ANSWER_FORMS, COGNITIVE_ACTIONS, DEMAND_LEVELS, Prompt
from lms.prompts.repository import create_prompt, list_prompts
from lms.scheduling.models import ReviewPolicy, ReviewSchedule, SchedulerDecision
from lms.scheduling.repository import (
    list_review_policies,
    list_review_schedules,
    list_scheduler_decisions,
)
from lms.scheduling.service import (
    DEFAULT_DAILY_CAP,
    ReviewQueueOverview,
    SchedulerSettings,
    get_review_queue_overview,
)
from lms.sources.models import SourceReference
from lms.sources.repository import list_source_references
from lms.ui.shell import empty_state, render_page

router = APIRouter(tags=["learner-ui"])
SessionDep = Annotated[Session, Depends(get_session)]
_STATIC_FILES = files("lms.ui.static")
_MANIFEST_CONTENT = _STATIC_FILES.joinpath("manifest.webmanifest").read_text()
_SERVICE_WORKER_CONTENT = _STATIC_FILES.joinpath("service-worker.js").read_text()


@router.get("/manifest.webmanifest")
def manifest_route() -> Response:
    """Serve the PWA manifest from the package static directory."""
    return Response(_MANIFEST_CONTENT, media_type="application/manifest+json")


@router.get("/service-worker.js")
def service_worker_route() -> Response:
    """Serve the service worker placeholder from the package static directory."""
    return Response(_SERVICE_WORKER_CONTENT, media_type="application/javascript")


@router.get("/app/learner", response_class=HTMLResponse)
def learner_app_route(
    session: SessionDep,
    learner_id: Annotated[str, Query(min_length=1, max_length=36)] = "learner-1",
) -> str:
    """Return the learner home dashboard."""
    return _dashboard_surface(session=session, learner_id=learner_id)


@router.get("/learn", response_class=HTMLResponse)
def learn_surface_route(
    session: SessionDep,
    learner_id: Annotated[str, Query(min_length=1, max_length=36)] = "learner-1",
    prompt_id: Annotated[str | None, Query(min_length=1, max_length=36)] = None,
) -> str:
    """Return the legacy Learn route for compatibility."""
    return _learn_surface(session=session, learner_id=learner_id, prompt_id=prompt_id)


def _learn_surface(
    *,
    session: Session,
    learner_id: str,
    prompt_id: str | None,
) -> str:
    """Return a mobile-friendly Learn surface wired to the attempt API."""
    prompt = session.get(Prompt, prompt_id) if prompt_id is not None else None
    prompt_body = _prompt_body(prompt) if prompt is not None else "No prompt selected."
    citations = _source_citation_items(prompt) if prompt is not None else []
    provenance = (
        _prompt_provenance(prompt) if prompt is not None else "No prompt provenance available."
    )
    attempt_summary = _latest_attempt_summary(session, learner_id=learner_id, prompt_id=prompt_id)

    return render_page(
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
            <p class="prompt-provenance">{escape(provenance)}</p>
          </section>
          <form class="attempt-form" method="post" action="/learn/attempts">
            <input type="hidden" name="learner_id" value="{escape(learner_id)}">
            <input type="hidden" name="prompt_id" value="{escape(prompt_id or "")}">
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
            <p>{escape(attempt_summary)}</p>
          </section>
          <section aria-labelledby="sources-heading" class="source-panel">
            <h2 id="sources-heading">Source citations after attempt</h2>
            <ul>{"".join(citations) if citations else "<li>No source citations linked.</li>"}</ul>
          </section>
        </main>
        """,
        active_path="/app/learner",
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
    prompt = session.get(Prompt, attempt.prompt_id)
    citations = _source_citation_items(prompt) if prompt is not None else []

    return render_page(
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
            <p>Confidence: {escape(_confidence_label(attempt.confidence_rating))}</p>
            <p>Correctness: pending scoring evidence.</p>
            <p>Review feedback and continue practice.</p>
          </section>
          <section aria-labelledby="sources-heading" class="source-panel">
            <h2 id="sources-heading">Source citations after attempt</h2>
            <ul>{"".join(citations) if citations else "<li>No source citations linked.</li>"}</ul>
          </section>
        </main>
        """,
        active_path="/app/learner",
    )


@router.get("/app/learner/reviews", response_class=HTMLResponse)
def learner_reviews_app_route(
    session: SessionDep,
    learner_id: Annotated[str, Query(min_length=1, max_length=36)] = "learner-1",
    daily_cap: Annotated[int, Query(ge=1, le=100)] = DEFAULT_DAILY_CAP,
) -> str:
    """Return the canonical learner review route."""
    return _review_surface(session=session, learner_id=learner_id, daily_cap=daily_cap)


@router.get("/app/learner/review", response_class=HTMLResponse)
def learner_review_app_route(
    session: SessionDep,
    learner_id: Annotated[str, Query(min_length=1, max_length=36)] = "learner-1",
    daily_cap: Annotated[int, Query(ge=1, le=100)] = DEFAULT_DAILY_CAP,
) -> str:
    """Return the legacy learner review route for compatibility."""
    return _review_surface(session=session, learner_id=learner_id, daily_cap=daily_cap)


@router.get("/review", response_class=HTMLResponse)
def review_surface_route(
    session: SessionDep,
    learner_id: Annotated[str, Query(min_length=1, max_length=36)] = "learner-1",
    daily_cap: Annotated[int, Query(ge=1, le=100)] = DEFAULT_DAILY_CAP,
) -> str:
    """Return the legacy Review route for compatibility."""
    return _review_surface(session=session, learner_id=learner_id, daily_cap=daily_cap)


def _review_surface(*, session: Session, learner_id: str, daily_cap: int) -> str:
    """Return a mobile-friendly Review surface with scheduler reason codes."""
    overview = get_review_queue_overview(
        session,
        learner_id=learner_id,
        settings=SchedulerSettings(daily_cap=daily_cap),
    )
    schedules = list_review_schedules(session, learner_id=learner_id, limit=50)
    decisions = list_scheduler_decisions(session, learner_id=learner_id, limit=50)
    policies = list_review_policies(session, limit=50)
    items = [
        (
            "<li class='queue-item'>"
            f"<strong>{escape(item.reason_code)} - "
            f"{escape(_queue_status_label(item.status, item.reason_code))}</strong>"
            f"<span>{escape(item.reason_explanation)}</span>"
            f"<small>Due {escape(_date_label(item.due_at))}; "
            f"node {escape(item.knowledge_node_id)}; priority {item.priority:.2f}</small>"
            f"{_attempt_link(session, item.source_attempt_id, learner_id=item.learner_id)}"
            "</li>"
        )
        for item in overview.items
    ]
    if not items:
        blocked_total = sum(
            1 for schedule in schedules if schedule.reason_code == "blocked-prerequisite"
        )
        empty_text = (
            "All review items are blocked by prerequisites."
            if blocked_total
            else "No due review items."
        )
        items.append(f"<li class='queue-item empty'>{escape(empty_text)}</li>")
    schedule_items = [_review_schedule_item(schedule) for schedule in schedules]
    if not schedule_items:
        schedule_items.append("<li class='queue-item empty'>No durable review schedules.</li>")
    decision_items = [_scheduler_decision_item(decision) for decision in decisions]
    if not decision_items:
        decision_items.append("<li class='queue-item empty'>No scheduler decisions recorded.</li>")
    policy_items = [_review_policy_item(policy) for policy in policies]
    if not policy_items:
        policy_items.append("<li class='queue-item empty'>No active review policies.</li>")

    return render_page(
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
            <ul class="review-queue">{"".join(items)}</ul>
          </section>
          <section aria-labelledby="schedule-heading">
            <h2 id="schedule-heading">Schedule detail</h2>
            <ul class="review-queue">{"".join(schedule_items)}</ul>
          </section>
          <section aria-labelledby="decision-heading">
            <h2 id="decision-heading">Scheduler decisions</h2>
            <ul class="review-queue">{"".join(decision_items)}</ul>
          </section>
          <section aria-labelledby="policy-heading">
            <h2 id="policy-heading">Review policy</h2>
            <ul class="review-queue">{"".join(policy_items)}</ul>
          </section>
          <section aria-labelledby="controls-heading">
            <h2 id="controls-heading">Review controls</h2>
            <button type="button" data-action="pause-review" disabled>Pause review</button>
            <button type="button" data-action="mark-stale" disabled>Mark stale</button>
            <button type="button" data-action="resume-review" disabled>Resume</button>
          </section>
        </main>
        """,
        active_path="/app/learner",
    )


def _review_schedule_item(schedule: ReviewSchedule) -> str:
    return (
        "<li class='queue-item'>"
        f"<strong>{escape(schedule.reason_code)} - {escape(schedule.schedule_state)}</strong>"
        f"<span>Due {escape(_date_label(schedule.due_at))}; "
        f"policy {escape(schedule.policy_version)}</span>"
        f"<small>node {escape(schedule.knowledge_node_id)}"
        f"{_optional_detail('type', schedule.knowledge_type)}"
        f"{_optional_detail('scope', schedule.ownership_scope)}</small>"
        "</li>"
    )


def _scheduler_decision_item(decision: SchedulerDecision) -> str:
    return (
        "<li class='queue-item'>"
        f"<strong>{escape(decision.reason_code)}</strong>"
        f"<span>{escape(decision.decision_rationale)}</span>"
        f"<small>policy {escape(decision.policy_version)}; "
        f"node {escape(decision.knowledge_node_id)}"
        f"{_optional_detail('support', decision.support_level)}</small>"
        "</li>"
    )


def _review_policy_item(policy: ReviewPolicy) -> str:
    setting_bits = ", ".join(f"{key}: {value}" for key, value in sorted(policy.settings.items()))
    setting_text = setting_bits or "No custom settings"
    return (
        "<li class='queue-item'>"
        f"<strong>{escape(policy.name)}</strong>"
        f"<span>{escape(policy.reason_code)}; version {escape(policy.policy_version)}</span>"
        f"<small>{escape(setting_text)}</small>"
        "</li>"
    )


def _attempt_link(session: Session, attempt_id: str | None, *, learner_id: str) -> str:
    if attempt_id is None:
        return ""
    attempt = session.get(Attempt, attempt_id)
    if attempt is None:
        return ""
    return (
        f'<a href="/app/learner?learner_id={escape(learner_id)}'
        f'&amp;prompt_id={escape(attempt.prompt_id)}">Open attempt</a>'
    )


def _optional_detail(label: str, value: str | None) -> str:
    return f"; {escape(label)} {escape(value)}" if value else ""


def _queue_status_label(status: str, reason_code: str) -> str:
    if reason_code == "blocked-prerequisite":
        return "blocked"
    if status == "pending":
        return "available"
    return status


def _date_label(value: object) -> str:
    isoformat = getattr(value, "isoformat", None)
    return isoformat(timespec="minutes") if callable(isoformat) else str(value)


@router.get("/app/author", response_class=HTMLResponse)
def author_app_route() -> str:
    """Return the author app index route."""
    return render_page(
        "Author",
        """
        <main class="surface author-surface">
          <header>
            <p class="eyebrow">Author workspace</p>
            <h1>Author</h1>
          </header>
          <section class="empty-state" aria-labelledby="author-start-heading">
            <h2 id="author-start-heading">Authoring tools</h2>
            <p>Create learning objects, feedback instruments, and transfer cases.</p>
            <nav aria-label="Author tools">
              <a href="/app/author/goals">Goals</a>
              <a href="/app/author/knowledge">Knowledge graph</a>
              <a href="/app/author/prompts">Prompts</a>
              <a href="/app/author/rubrics">Rubrics</a>
              <a href="/app/author/feedback-templates">Feedback templates</a>
              <a href="/app/author/cases">Cases</a>
            </nav>
          </section>
        </main>
        """,
        active_path="/app/author",
    )


@router.get("/app/author/goals", response_class=HTMLResponse)
def author_goals_route(
    session: SessionDep,
    learner_id: Annotated[str, Query(min_length=1, max_length=36)] = "learner-1",
    ownership_scope: Annotated[str, Query()] = "personal",
) -> str:
    """Return goal authoring forms and current goals."""
    return _author_goals_surface(
        session=session,
        learner_id=learner_id,
        ownership_scope=ownership_scope,
        message=None,
        error=None,
    )


@router.post("/app/author/goals", response_class=HTMLResponse)
async def create_author_goal_route(request: Request, session: SessionDep) -> str:
    """Create a learning goal from the author form."""
    form = await _read_form(request)
    learner_id = form.get("learner_id", "")
    ownership_scope = form.get("ownership_scope", "personal")
    try:
        create_learning_goal(
            session,
            learner_id=learner_id,
            title=form.get("title", ""),
            knowledge_type=form.get("knowledge_type", "conceptual"),
            target_node_ids=_split_ids(form.get("target_node_ids", "")),
            ownership_scope=ownership_scope,
            status=form.get("status", "active"),
        )
        session.commit()
    except ValueError as exc:
        session.rollback()
        return _author_goals_surface(
            session=session,
            learner_id=learner_id,
            ownership_scope=ownership_scope,
            message=None,
            error=str(exc),
        )
    return _author_goals_surface(
        session=session,
        learner_id=learner_id,
        ownership_scope=ownership_scope,
        message="Goal saved.",
        error=None,
    )


@router.get("/app/author/knowledge", response_class=HTMLResponse)
def author_knowledge_route(
    session: SessionDep,
    ownership_scope: Annotated[str, Query()] = "personal",
) -> str:
    """Return knowledge node and edge authoring forms."""
    return _author_knowledge_surface(
        session=session,
        ownership_scope=ownership_scope,
        message=None,
        error=None,
    )


@router.post("/app/author/knowledge/nodes", response_class=HTMLResponse)
async def create_author_node_route(request: Request, session: SessionDep) -> str:
    """Create a knowledge node from the author form."""
    form = await _read_form(request)
    ownership_scope = form.get("ownership_scope", "personal")
    try:
        create_knowledge_node(
            session,
            title=form.get("title", ""),
            description=form.get("description") or None,
            knowledge_type=form.get("knowledge_type", "conceptual"),
            scope=ownership_scope,
            status=form.get("status", "draft"),
            actor_id="author-ui",
            source_reference_id=form.get("source_reference_id") or None,
            source_subsystem="author-ui",
        )
        session.commit()
    except ValueError as exc:
        session.rollback()
        return _author_knowledge_surface(
            session=session,
            ownership_scope=ownership_scope,
            message=None,
            error=str(exc),
        )
    return _author_knowledge_surface(
        session=session,
        ownership_scope=ownership_scope,
        message="Knowledge node saved.",
        error=None,
    )


@router.post("/app/author/knowledge/edges", response_class=HTMLResponse)
async def create_author_edge_route(request: Request, session: SessionDep) -> str:
    """Create a knowledge edge from the author form."""
    form = await _read_form(request)
    ownership_scope = form.get("ownership_scope", "personal")
    try:
        create_knowledge_edge(
            session,
            source_node_id=form.get("source_node_id", ""),
            target_node_id=form.get("target_node_id", ""),
            edge_type=form.get("edge_type", "prerequisite"),
            scope=ownership_scope,
            target_scope=form.get("target_scope") or ownership_scope,
            is_graph_reference=form.get("is_graph_reference") == "true",
            confidence=_optional_float(form.get("confidence")),
            status=form.get("status", "draft"),
            actor_id="author-ui",
            source_subsystem="author-ui",
        )
        session.commit()
    except ValueError as exc:
        session.rollback()
        return _author_knowledge_surface(
            session=session,
            ownership_scope=ownership_scope,
            message=None,
            error=str(exc),
        )
    return _author_knowledge_surface(
        session=session,
        ownership_scope=ownership_scope,
        message="Knowledge edge saved.",
        error=None,
    )


@router.get("/app/author/prompts", response_class=HTMLResponse)
def author_prompts_route(
    session: SessionDep,
    ownership_scope: Annotated[str, Query()] = "personal",
) -> str:
    """Return prompt authoring forms and current prompts."""
    return _author_prompts_surface(
        session=session,
        ownership_scope=ownership_scope,
        message=None,
        error=None,
    )


@router.post("/app/author/prompts", response_class=HTMLResponse)
async def create_author_prompt_route(request: Request, session: SessionDep) -> str:
    """Create a prompt from the author form."""
    form = await _read_form(request)
    ownership_scope = form.get("ownership_scope", "personal")
    try:
        create_prompt(
            session,
            target_node_id=form.get("target_node_id", ""),
            learning_goal_id=form.get("learning_goal_id", ""),
            knowledge_type=form.get("knowledge_type", "conceptual"),
            intended_cognitive_action=form.get("intended_cognitive_action", "explain"),
            demand_level=form.get("demand_level", "medium"),
            expected_answer_form=form.get("expected_answer_form", "short-text"),
            body=form.get("body", ""),
            source_reference_ids=_split_ids(form.get("source_reference_ids", "")),
            authoring_method="human-authored",
            authoring_actor="author-ui",
        )
        session.commit()
    except ValueError as exc:
        session.rollback()
        return _author_prompts_surface(
            session=session,
            ownership_scope=ownership_scope,
            message=None,
            error=str(exc),
        )
    return _author_prompts_surface(
        session=session,
        ownership_scope=ownership_scope,
        message="Prompt saved as draft.",
        error=None,
    )


@router.get("/app/author/rubrics", response_class=HTMLResponse)
def author_rubrics_route(session: SessionDep) -> str:
    """Return rubric authoring forms backed by durable rubric repositories."""
    return _author_rubrics_page(session)


@router.post("/app/author/rubrics", response_class=HTMLResponse)
async def create_author_rubric_route(request: Request, session: SessionDep) -> str:
    """Create a rubric with one initial criterion from the authoring surface."""
    form = _form_dict(await request.body())
    notice = "Rubric created."
    try:
        create_rubric(
            session,
            title=_required_text(form, "title"),
            description=_optional_text(form.get("description")),
            ownership_scope=_required_text(form, "ownership_scope"),
            status=_required_text(form, "status"),
            authoring_actor=_required_text(form, "authoring_actor"),
            prompt_id=_optional_text(form.get("prompt_id")),
            knowledge_node_id=_optional_text(form.get("knowledge_node_id")),
            criteria=[
                {
                    "criterion_order": _required_int(form, "criterion_order"),
                    "description": _required_text(form, "criterion_description"),
                    "max_points": _required_float(form, "max_points"),
                    "validity_scope": _optional_text(form.get("validity_scope")),
                    "performance_levels": _json_object(form.get("performance_levels")),
                }
            ],
        )
        session.commit()
    except (ValueError, JSONDecodeError) as exc:
        session.rollback()
        notice = str(exc)
    return _author_rubrics_page(session, notice=notice)


@router.get("/app/author/feedback-templates", response_class=HTMLResponse)
def author_feedback_templates_route(session: SessionDep) -> str:
    """Return feedback template authoring and preview controls."""
    return _author_templates_page(session)


@router.post("/app/author/feedback-templates", response_class=HTMLResponse)
async def create_author_feedback_template_route(request: Request, session: SessionDep) -> str:
    """Create a reusable feedback template from the authoring surface."""
    form = _form_dict(await request.body())
    notice = "Feedback template created."
    try:
        create_feedback_template(
            session,
            name=_required_text(form, "name"),
            template_body=_required_text(form, "template_body"),
            placeholder_schema={"required": _csv_values(form.get("required_placeholders", ""))},
            feedback_level=_required_text(form, "feedback_level"),
            action_type=_required_text(form, "action_type"),
            ownership_scope=_required_text(form, "ownership_scope"),
            status=_required_text(form, "status"),
            authoring_actor=_required_text(form, "authoring_actor"),
        )
        session.commit()
    except ValueError as exc:
        session.rollback()
        notice = str(exc)
    return _author_templates_page(session, notice=notice)


@router.post("/app/author/feedback-templates/preview", response_class=HTMLResponse)
async def preview_author_feedback_template_route(request: Request, session: SessionDep) -> str:
    """Render a feedback template preview using supplied placeholder values."""
    form = _form_dict(await request.body())
    notice = ""
    preview = ""
    try:
        template = get_feedback_template(session, _required_text(form, "template_id"))
        if template is None:
            raise ValueError("feedback template was not found")
        preview = render_feedback_template(template, _json_object(form.get("values_json")))
        notice = "Preview rendered."
    except (ValueError, JSONDecodeError) as exc:
        notice = str(exc)
    return _author_templates_page(session, notice=notice, preview=preview)


@router.get("/app/author/cases", response_class=HTMLResponse)
def author_cases_route(session: SessionDep) -> str:
    """Return transfer case authoring controls."""
    return _author_cases_page(session)


@router.post("/app/author/cases", response_class=HTMLResponse)
async def create_author_case_route(request: Request, session: SessionDep) -> str:
    """Create a transfer case shell with nested step/evidence/decision data."""
    form = _form_dict(await request.body())
    notice = "Case created."
    try:
        case = create_case(
            session,
            title=_required_text(form, "title"),
            description=_optional_text(form.get("description")),
            ownership_scope=_required_text(form, "ownership_scope"),
            rubric_id=_optional_text(form.get("rubric_id")),
            knowledge_node_id=_optional_text(form.get("knowledge_node_id")),
            status=_required_text(form, "status"),
            steps=[
                {
                    "step_order": _required_int(form, "step_order"),
                    "title": _required_text(form, "step_title"),
                    "prompt": _required_text(form, "step_prompt"),
                    "expected_work_product": _optional_text(form.get("expected_work_product")),
                }
            ],
            evidence_packets=[
                {
                    "title": _required_text(form, "evidence_title"),
                    "summary": _optional_text(form.get("evidence_summary")),
                    "packet_metadata": _json_object(form.get("packet_metadata")),
                }
            ],
        )
        session.flush()
        case = get_case(session, case.id) or case
        add_decision_point(
            session,
            case_step_id=case.steps[0].id,
            title=_required_text(form, "decision_title"),
            prompt=_required_text(form, "decision_prompt"),
            decision_type=_required_text(form, "decision_type"),
            evidence_packet_id=case.evidence_packets[0].id,
            options=_json_list(form.get("decision_options")),
        )
        session.commit()
    except (ValueError, JSONDecodeError) as exc:
        session.rollback()
        notice = str(exc)
    return _author_cases_page(session, notice=notice)


def _dashboard_surface(*, session: Session, learner_id: str) -> str:
    """Return the learner home dashboard aggregating the learner's own state."""
    goals = list_learning_goals_for_learner(session, learner_id=learner_id)
    mastery = mastery_estimates_for_learner(session, learner_id)
    review = get_review_queue_overview(session, learner_id=learner_id)
    actions = list_feedback_actions(session, learner_id=learner_id, status="open")
    evidence = _recent_evidence(session, learner_id=learner_id)
    targets = list_capability_targets(session, learner_id=learner_id)
    plans = list_maintenance_plans(session, learner_id=learner_id)

    return render_page(
        "Learner",
        f"""
        <main class="surface learner-dashboard">
          <header>
            <p class="eyebrow">Your learning home</p>
            <h1>Learner dashboard</h1>
            <p>Everything below reflects your own evidence and goals. Counts are
            informational, not scores.</p>
          </header>
          {_dashboard_quick_links()}
          <div class="dashboard-grid">
            {_next_actions_panel(actions)}
            {_reviews_panel(review)}
            {_recent_evidence_panel(evidence)}
            {_goals_panel(goals)}
            {_mastery_panel(session, mastery)}
            {_capability_panel(targets)}
            {_maintenance_panel(plans)}
          </div>
        </main>
        """,
        active_path="/app/learner",
    )


def _dashboard_quick_links() -> str:
    return (
        '<nav class="dashboard-links" aria-label="Dashboard quick links"><ul>'
        '<li><a href="/learn">Start or continue an attempt</a></li>'
        '<li><a href="/app/learner/review">Open the review queue</a></li>'
        '<li><a href="#next-actions">See feedback actions</a></li>'
        '<li><a href="#capability">See capability targets</a></li>'
        "</ul></nav>"
    )


def _panel(*, panel_id: str, heading: str, intro: str, body: str) -> str:
    heading_id = f"{panel_id}-heading"
    intro_html = f"<p>{intro}</p>" if intro else ""
    return (
        f'<section class="panel" id="{panel_id}" aria-labelledby="{heading_id}">'
        f'<h2 id="{heading_id}">{escape(heading)}</h2>{intro_html}{body}</section>'
    )


def _next_actions_panel(actions: Sequence[FeedbackAction]) -> str:
    if not actions:
        return _panel(
            panel_id="next-actions",
            heading="Next actions",
            intro="",
            body=empty_state(
                "No next actions",
                "You have no open follow-up actions right now. New next actions appear "
                "here after you get feedback on an attempt.",
            ),
        )
    items = []
    for action in actions:
        due = _due_suffix(action.due_at)
        instructions = escape(action.instructions or "")
        items.append(
            "<li class='panel-item'>"
            f"<strong>{escape(action.title)}</strong>"
            f"<span>{escape(action.action_type)} · {escape(action.status)}{due}</span>"
            + (f"<small>{instructions}</small>" if instructions else "")
            + "</li>"
        )
    return _panel(
        panel_id="next-actions",
        heading="Next actions",
        intro='<a href="/learn">Start or continue an attempt</a>',
        body=f'<ul class="panel-list">{"".join(items)}</ul>',
    )


def _reviews_panel(review: ReviewQueueOverview) -> str:
    items = review.items
    if not items:
        return _panel(
            panel_id="reviews",
            heading="Due reviews",
            intro="",
            body=empty_state(
                "No reviews due",
                "Nothing is due for review today. Scheduled reviews show up here; the "
                "backlog total is informational, not an obligation score.",
            ),
        )
    rendered = []
    for item in items:
        rendered.append(
            "<li class='panel-item'>"
            f"<strong>{escape(item.reason_code)}</strong>"
            f"<span>{escape(item.reason_explanation)}</span>"
            f"<small>node {escape(item.knowledge_node_id)}; priority {item.priority:.2f}</small>"
            "</li>"
        )
    intro = (
        '<a href="/app/learner/review">Open the review queue</a>'
        f"<br><span class='note'>{escape(review.backlog_note)}</span>"
    )
    return _panel(
        panel_id="reviews",
        heading="Due reviews",
        intro=intro,
        body=f'<ul class="panel-list">{"".join(rendered)}</ul>',
    )


def _recent_evidence_panel(evidence: list[EvidenceRecord]) -> str:
    if not evidence:
        return _panel(
            panel_id="recent-evidence",
            heading="Recent evidence",
            intro="",
            body=empty_state(
                "No recent evidence",
                "No attempts are recorded yet. Your recent evidence will appear here "
                "after your first attempt.",
            ),
        )
    items = []
    for record in evidence:
        items.append(
            "<li class='panel-item'>"
            f"<strong>{escape(record.knowledge_node_id)}</strong>"
            f"<span>{escape(_evidence_outcome(record))}</span>"
            f"<small>{escape(_support_note(record))}observed "
            f"{escape(_format_day(record.observed_at))}</small>"
            "</li>"
        )
    return _panel(
        panel_id="recent-evidence",
        heading="Recent evidence",
        intro="",
        body=f'<ul class="panel-list">{"".join(items)}</ul>',
    )


def _goals_panel(goals: Sequence[LearningGoal]) -> str:
    if not goals:
        return _panel(
            panel_id="goals",
            heading="Goals",
            intro="",
            body=empty_state(
                "No goals yet",
                "You have not set any learning goals yet. Add a goal whenever you are "
                "ready to focus your practice.",
            ),
        )
    items = []
    for goal in goals:
        items.append(
            "<li class='panel-item'>"
            f"<strong>{escape(goal.title)}</strong>"
            f"<span>{escape(goal.knowledge_type)} · {escape(goal.status)}</span>"
            "</li>"
        )
    return _panel(
        panel_id="goals",
        heading="Goals",
        intro="",
        body=f'<ul class="panel-list">{"".join(items)}</ul>',
    )


def _mastery_panel(session: Session, mastery: list[dict[str, Any]]) -> str:
    if not mastery:
        return _panel(
            panel_id="mastery",
            heading="Mastery summary",
            intro="",
            body=empty_state(
                "No mastery estimates yet",
                "Mastery estimates appear once you have collected evidence. Estimates "
                "are model-based and update as you practice.",
            ),
        )
    items = []
    for estimate in mastery:
        node_id = str(estimate["knowledge_node_id"])
        title = _node_title(session, node_id)
        current = float(estimate["current_estimate"])
        evidence_count = estimate["evidence_count"]
        items.append(
            "<li class='panel-item'>"
            f"<strong>{escape(title)}</strong>"
            f"<span>estimate {current:.0%}; evidence count {escape(str(evidence_count))}</span>"
            "</li>"
        )
    attribution = escape(str(mastery[0]["model_attribution"]))
    return _panel(
        panel_id="mastery",
        heading="Mastery summary",
        intro="",
        body=(
            f'<ul class="panel-list">{"".join(items)}</ul>'
            f'<p class="note">Model attribution: {attribution}</p>'
        ),
    )


def _capability_panel(targets: Sequence[CapabilityTarget]) -> str:
    if not targets:
        return _panel(
            panel_id="capability",
            heading="Capability targets",
            intro="",
            body=empty_state(
                "No capability targets yet",
                "No capability targets yet. Targets help you track transfer-ready "
                "capabilities at your own pace.",
            ),
        )
    items = []
    for target in targets:
        description = escape(target.description or "")
        items.append(
            "<li class='panel-item'>"
            f"<strong>{escape(target.title)}</strong>"
            f"<span>{escape(target.status)} · confidence threshold "
            f"{float(target.confidence_threshold):.0%}</span>"
            + (f"<small>{description}</small>" if description else "")
            + "</li>"
        )
    return _panel(
        panel_id="capability",
        heading="Capability targets",
        intro="",
        body=f'<ul class="panel-list">{"".join(items)}</ul>',
    )


def _maintenance_panel(plans: Sequence[MaintenancePlan]) -> str:
    steps: list[dict[str, Any]] = []
    for plan in plans:
        steps.extend(plan.plan_steps)
    if not steps:
        return _panel(
            panel_id="maintenance",
            heading="Maintenance plan",
            intro="",
            body=empty_state(
                "No maintenance-plan steps yet",
                "No maintenance-plan steps yet. Steps are generated from a gap analysis "
                "when there is something specific to maintain.",
            ),
        )
    items = []
    for step in steps:
        number = escape(str(step.get("step_number", "")))
        action_type = escape(str(step.get("action_type", "review")))
        rationale = escape(str(step.get("rationale", "")))
        status = escape(str(step.get("status", "planned")))
        items.append(
            "<li class='panel-item'>"
            f"<strong>Step {number}: {action_type}</strong>"
            f"<span>{rationale}</span>"
            f"<small>status {status}</small>"
            "</li>"
        )
    return _panel(
        panel_id="maintenance",
        heading="Maintenance plan",
        intro="",
        body=f'<ul class="panel-list">{"".join(items)}</ul>',
    )


def _recent_evidence(session: Session, *, learner_id: str, limit: int = 5) -> list[EvidenceRecord]:
    return list(
        session.scalars(
            select(EvidenceRecord)
            .where(EvidenceRecord.learner_id == learner_id)
            .order_by(EvidenceRecord.observed_at.desc(), EvidenceRecord.id)
            .limit(limit)
        )
    )


def _evidence_outcome(record: EvidenceRecord) -> str:
    if record.normalized_score is not None:
        return f"score {float(record.normalized_score):.0%}"
    if record.correctness is True:
        return "marked correct"
    if record.correctness is False:
        return "needs another pass"
    return "evidence recorded"


def _support_note(record: EvidenceRecord) -> str:
    markers: list[str] = []
    if record.hint_used:
        markers.append("hint")
    if record.reference_accessed:
        markers.append("reference")
    if record.support_level not in ("none", ""):
        markers.append(f"support {record.support_level}")
    return f"used {', '.join(markers)}; " if markers else ""


def _node_title(session: Session, node_id: str) -> str:
    node = session.get(KnowledgeNode, node_id)
    return node.title if node is not None else node_id


def _due_suffix(due_at: datetime | None) -> str:
    return f"; due {_format_day(due_at)}" if due_at is not None else ""


def _format_day(value: datetime | None) -> str:
    return value.date().isoformat() if value is not None else "unknown"


def _prompt_body(prompt: Prompt) -> str:
    if not prompt.versions:
        return "Prompt wording unavailable."
    return prompt.versions[-1].body


def _prompt_provenance(prompt: Prompt) -> str:
    return (
        f"Provenance: {prompt.authoring_method}; "
        f"author {prompt.authoring_actor}; reviewer {prompt.reviewing_actor}."
    )


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


def _latest_attempt_summary(session: Session, *, learner_id: str, prompt_id: str | None) -> str:
    if prompt_id is None:
        return "Feedback appears after an attempt is recorded through the attempts API."
    attempt = session.scalars(
        select(Attempt)
        .where(Attempt.learner_id == learner_id, Attempt.prompt_id == prompt_id)
        .order_by(Attempt.created_at.desc())
        .limit(1)
    ).first()
    if attempt is None:
        return "Feedback appears after an attempt is recorded through the attempts API."

    correctness = next(
        (
            record.correctness
            for record in attempt.evidence_records
            if record.correctness is not None
        ),
        None,
    )
    correctness_label = (
        "pending scoring evidence"
        if correctness is None
        else "correct"
        if correctness
        else "incorrect"
    )
    return (
        f"Latest evidence: confidence {_confidence_label(attempt.confidence_rating)}; "
        f"correctness {correctness_label}."
    )


def _confidence_label(value: int | None) -> str:
    return "not recorded" if value is None else f"{value}/5"


def _optional_int(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


async def _read_form(request: Request) -> dict[str, str]:
    raw_form = parse_qs((await request.body()).decode(), keep_blank_values=True)
    return {key: values[-1] for key, values in raw_form.items()}


def _author_goals_surface(
    *,
    session: Session,
    learner_id: str,
    ownership_scope: str,
    message: str | None,
    error: str | None,
) -> str:
    goals = list_learning_goals_for_learner(
        session,
        learner_id=learner_id,
        ownership_scope=ownership_scope,
    )
    nodes = list_knowledge_nodes(session, scope=ownership_scope)
    goal_items = [
        (
            "<li>"
            f"<strong>{escape(goal.title)}</strong>"
            f"<span>{escape(goal.status)}; {escape(goal.knowledge_type)}; "
            f"{len(goal.target_nodes)} target nodes</span>"
            "</li>"
        )
        for goal in goals
    ] or ["<li class='empty'>No goals yet.</li>"]

    return render_page(
        "Author Goals",
        f"""
        <main class="surface author-surface">
          {_notice(message, error)}
          <header>
            <p class="eyebrow">Author</p>
            <h1>Goals</h1>
          </header>
          <form method="post" action="/app/author/goals">
            <input type="hidden" name="learner_id" value="{escape(learner_id)}">
            {_select("ownership_scope", ("personal", "institutional"), ownership_scope)}
            <label for="goal-title">Goal title</label>
            <input id="goal-title" name="title" required>
            {_select("knowledge_type", KNOWLEDGE_TYPES, "conceptual")}
            {_select("status", GOAL_STATUSES, "active")}
            <label for="target-node-ids">Target node ids</label>
            <input id="target-node-ids" name="target_node_ids"
              aria-describedby="available-nodes">
            <small id="available-nodes">{escape(_node_hint(nodes))}</small>
            <button type="submit">Save goal</button>
          </form>
          <section aria-labelledby="goal-list-heading">
            <h2 id="goal-list-heading">Current goals</h2>
            <ul>{"".join(goal_items)}</ul>
          </section>
        </main>
        """,
        active_path="/app/author",
    )


def _author_knowledge_surface(
    *,
    session: Session,
    ownership_scope: str,
    message: str | None,
    error: str | None,
) -> str:
    nodes = list_knowledge_nodes(session, scope=ownership_scope)
    edges = list_knowledge_edges(session, scope=ownership_scope)
    node_items = [
        (
            "<li>"
            f"<strong>{escape(node.title)}</strong>"
            f"<span>{escape(node.status)}; {escape(node.knowledge_type)}; "
            f"{escape(node.ownership_scope)}; id {escape(node.id)}</span>"
            "</li>"
        )
        for node in nodes
    ] or ["<li class='empty'>No knowledge nodes yet.</li>"]
    edge_items = [
        (
            "<li>"
            f"<strong>{escape(edge.edge_type)}</strong>"
            f"<span>{escape(edge.source_node_id)} to {escape(edge.target_node_id)}; "
            f"{escape(edge.status)}; confidence {_confidence_value(edge.confidence)}</span>"
            "</li>"
        )
        for edge in edges
    ] or ["<li class='empty'>No knowledge edges yet.</li>"]

    return render_page(
        "Author Knowledge",
        f"""
        <main class="surface author-surface">
          {_notice(message, error)}
          <header>
            <p class="eyebrow">Author</p>
            <h1>Knowledge graph</h1>
          </header>
          <section aria-labelledby="node-form-heading">
            <h2 id="node-form-heading">Node</h2>
            <form method="post" action="/app/author/knowledge/nodes">
              {_select("ownership_scope", ("personal", "institutional"), ownership_scope, id_prefix="node")}
              <label for="node-title">Title</label>
              <input id="node-title" name="title" required>
              <label for="node-description">Description</label>
              <textarea id="node-description" name="description" rows="3"></textarea>
              {_select("knowledge_type", KNOWLEDGE_TYPES, "conceptual", id_prefix="node")}
              {_select("status", NODE_STATUSES, "draft", id_prefix="node")}
              <label for="source-reference-id">Source reference id</label>
              <input id="source-reference-id" name="source_reference_id">
              <button type="submit">Save node</button>
            </form>
          </section>
          <section aria-labelledby="edge-form-heading">
            <h2 id="edge-form-heading">Edge</h2>
            <form method="post" action="/app/author/knowledge/edges">
              {_select("ownership_scope", ("personal", "institutional"), ownership_scope, id_prefix="edge")}
              <label for="source-node-id">Source node id</label>
              <input id="source-node-id" name="source_node_id" required>
              <label for="target-node-id">Target node id</label>
              <input id="target-node-id" name="target_node_id" required>
              {_select("target_scope", ("personal", "institutional"), ownership_scope, id_prefix="edge")}
              {_select("edge_type", EDGE_TYPES, "prerequisite", id_prefix="edge")}
              {_select("status", EDGE_STATUSES, "draft", id_prefix="edge")}
              <label for="confidence">Confidence</label>
              <input id="confidence" name="confidence" inputmode="decimal">
              <label class="check">
                <input type="checkbox" name="is_graph_reference" value="true">
                Allow explicit cross-scope graph reference
              </label>
              <button type="submit">Save edge</button>
            </form>
          </section>
          <section aria-labelledby="node-list-heading">
            <h2 id="node-list-heading">Nodes</h2>
            <ul>{"".join(node_items)}</ul>
          </section>
          <section aria-labelledby="edge-list-heading">
            <h2 id="edge-list-heading">Edges</h2>
            <ul>{"".join(edge_items)}</ul>
          </section>
        </main>
        """,
        active_path="/app/author",
    )


def _author_prompts_surface(
    *,
    session: Session,
    ownership_scope: str,
    message: str | None,
    error: str | None,
) -> str:
    nodes = list_knowledge_nodes(session, scope=ownership_scope, status="published")
    sources = list_source_references(session)
    prompts = list_prompts(session)
    prompt_items = [
        (
            "<li>"
            f"<strong>{escape(_prompt_body(prompt))}</strong>"
            f"<span>{escape(prompt.status)}; {escape(prompt.demand_level)}; "
            f"{escape(prompt.intended_cognitive_action)}; "
            f"provenance {escape(_prompt_provenance(prompt))}</span>"
            "</li>"
        )
        for prompt in prompts
    ] or ["<li class='empty'>No prompts yet.</li>"]

    return render_page(
        "Author Prompts",
        f"""
        <main class="surface author-surface">
          {_notice(message, error)}
          <header>
            <p class="eyebrow">Author</p>
            <h1>Prompts</h1>
          </header>
          <form method="post" action="/app/author/prompts">
            {_select("ownership_scope", ("personal", "institutional"), ownership_scope)}
            <label for="learning-goal-id">Learning goal id</label>
            <input id="learning-goal-id" name="learning_goal_id" required>
            <label for="target-node-id">Published target node id</label>
            <input id="target-node-id" name="target_node_id" required
              aria-describedby="published-node-hint">
            <small id="published-node-hint">{escape(_node_hint(nodes))}</small>
            {_select("knowledge_type", KNOWLEDGE_TYPES, "conceptual")}
            {_select("intended_cognitive_action", COGNITIVE_ACTIONS, "explain")}
            {_select("demand_level", DEMAND_LEVELS, "medium")}
            {_select("expected_answer_form", ANSWER_FORMS, "short-text")}
            <label for="source-reference-ids">Source reference ids</label>
            <input id="source-reference-ids" name="source_reference_ids" required
              aria-describedby="source-reference-hint">
            <small id="source-reference-hint">{escape(_source_hint(sources))}</small>
            <label for="prompt-body">Prompt body</label>
            <textarea id="prompt-body" name="body" rows="5" required></textarea>
            <button type="submit">Save prompt</button>
          </form>
          <section aria-labelledby="prompt-list-heading">
            <h2 id="prompt-list-heading">Current prompts</h2>
            <ul>{"".join(prompt_items)}</ul>
          </section>
        </main>
        """,
        active_path="/app/author",
    )


def _author_rubrics_page(session: Session, *, notice: str | None = None) -> str:
    rubrics = list_rubrics(session)
    items = [
        (
            "<li>"
            f"<strong>{escape(rubric.title)}</strong>"
            f"<span>{escape(rubric.ownership_scope)} scope; {escape(rubric.status)}; "
            f"{len(rubric.criteria)} criteria</span>"
            f"<small>Linked prompt: {escape(rubric.prompt_id or 'none')} | "
            f"source node: {escape(rubric.knowledge_node_id or 'none')}</small>"
            "</li>"
        )
        for rubric in rubrics
    ]
    return render_page(
        "Author rubrics",
        f"""
        <main class="surface author-surface">
          {_author_header("Rubrics")}
          {_notice(notice)}
          <form method="post" action="/app/author/rubrics">
            <label for="title">Rubric title</label>
            <input id="title" name="title" required>
            <label for="description">Description</label>
            <textarea id="description" name="description" rows="2"></textarea>
            {_scope_status_actor_fields()}
            <label for="prompt_id">Linked prompt</label>
            <input id="prompt_id" name="prompt_id">
            <label for="knowledge_node_id">Linked source node</label>
            <input id="knowledge_node_id" name="knowledge_node_id">
            <fieldset>
              <legend>Criterion</legend>
              <label for="criterion_order">Order</label>
              <input id="criterion_order" name="criterion_order" type="number" min="1" value="1" required>
              <label for="criterion_description">Description</label>
              <textarea id="criterion_description" name="criterion_description" rows="3" required></textarea>
              <label for="max_points">Max points</label>
              <input id="max_points" name="max_points" type="number" min="0.1" step="0.1" value="4" required>
              <label for="validity_scope">Validity scope</label>
              <input id="validity_scope" name="validity_scope">
              <label for="performance_levels">Performance levels JSON</label>
              <textarea id="performance_levels" name="performance_levels" rows="3">{{"meets": "Complete and sourced"}}</textarea>
            </fieldset>
            <button type="submit">Create rubric</button>
          </form>
          <section aria-labelledby="rubrics-list-heading">
            <h2 id="rubrics-list-heading">Rubric library</h2>
            {"<ul class='author-list'>" + "".join(items) + "</ul>" if items else empty_state("No rubrics", "Create the first rubric to make prompt and case scoring selectable.")}
          </section>
        </main>
        """,
        active_path="/app/author",
    )


def _author_templates_page(
    session: Session, *, notice: str | None = None, preview: str = ""
) -> str:
    templates = list_feedback_templates(session)
    items = [
        (
            "<li>"
            f"<strong>{escape(template.name)}</strong>"
            f"<span>{escape(template.ownership_scope)} scope; {escape(template.status)}; "
            f"{escape(template.feedback_level)} feedback</span>"
            f"<small>ID {escape(template.id)} | placeholders "
            f"{escape(', '.join(template.placeholder_schema.get('required', [])) or 'none')}</small>"
            "</li>"
        )
        for template in templates
    ]
    options = "".join(
        f'<option value="{escape(template.id)}">{escape(template.name)}</option>'
        for template in templates
    )
    return render_page(
        "Author feedback templates",
        f"""
        <main class="surface author-surface">
          {_author_header("Feedback templates")}
          {_notice(notice)}
          <form method="post" action="/app/author/feedback-templates">
            <label for="name">Template name</label>
            <input id="name" name="name" required>
            <label for="template_body">Template body</label>
            <textarea id="template_body" name="template_body" rows="4" required>Focus next on {{next_action}} because {{gap}}.</textarea>
            <label for="required_placeholders">Required placeholders</label>
            <input id="required_placeholders" name="required_placeholders" value="gap,next_action">
            <label for="feedback_level">Feedback level</label>
            <select id="feedback_level" name="feedback_level">
              <option value="coaching">coaching</option>
              <option value="remediation">remediation</option>
              <option value="review">review</option>
            </select>
            <label for="action_type">Action type</label>
            <select id="action_type" name="action_type">
              <option value="retry">retry</option>
              <option value="revision">revision</option>
              <option value="prerequisite-remediation">prerequisite-remediation</option>
            </select>
            {_scope_status_actor_fields()}
            <button type="submit">Create template</button>
          </form>
          <form method="post" action="/app/author/feedback-templates/preview">
            <label for="template_id">Template preview</label>
            <select id="template_id" name="template_id" required>{options}</select>
            <label for="values_json">Placeholder values JSON</label>
            <textarea id="values_json" name="values_json" rows="3">{{"gap": "cite the source", "next_action": "revise the evidence paragraph"}}</textarea>
            <button type="submit">Render preview</button>
          </form>
          {_preview(preview)}
          <section aria-labelledby="templates-list-heading">
            <h2 id="templates-list-heading">Template library</h2>
            {"<ul class='author-list'>" + "".join(items) + "</ul>" if items else empty_state("No feedback templates", "Create a template before testing placeholder rendering.")}
          </section>
        </main>
        """,
        active_path="/app/author",
    )


def _author_cases_page(session: Session, *, notice: str | None = None) -> str:
    cases = list_cases(session)
    rubrics = list_rubrics(session)
    rubric_options = '<option value="">None</option>' + "".join(
        f'<option value="{escape(rubric.id)}">{escape(rubric.title)}</option>' for rubric in rubrics
    )
    items = [
        (
            "<li>"
            f"<strong>{escape(case.title)}</strong>"
            f"<span>{escape(case.ownership_scope)} scope; {escape(case.status)}; "
            f"{len(case.steps)} steps; {len(case.evidence_packets)} evidence packets</span>"
            f"<small>Rubric: {escape(case.rubric_id or 'none')} | "
            f"source node: {escape(case.knowledge_node_id or 'none')}</small>"
            "</li>"
        )
        for case in cases
    ]
    return render_page(
        "Author cases",
        f"""
        <main class="surface author-surface">
          {_author_header("Cases")}
          {_notice(notice)}
          <form method="post" action="/app/author/cases">
            <label for="case-title">Case title</label>
            <input id="case-title" name="title" required>
            <label for="case-description">Description</label>
            <textarea id="case-description" name="description" rows="2"></textarea>
            {_scope_status_actor_fields(include_actor=False)}
            <label for="rubric_id">Linked rubric</label>
            <select id="rubric_id" name="rubric_id">{rubric_options}</select>
            <label for="case-node">Linked source node</label>
            <input id="case-node" name="knowledge_node_id">
            <fieldset>
              <legend>Step</legend>
              <label for="step_order">Order</label>
              <input id="step_order" name="step_order" type="number" min="1" value="1" required>
              <label for="step_title">Step title</label>
              <input id="step_title" name="step_title" required>
              <label for="step_prompt">Step prompt</label>
              <textarea id="step_prompt" name="step_prompt" rows="3" required></textarea>
              <label for="expected_work_product">Expected work product</label>
              <input id="expected_work_product" name="expected_work_product" placeholder="memo, rationale, or analysis">
            </fieldset>
            <fieldset>
              <legend>Evidence packet</legend>
              <label for="evidence_title">Evidence title</label>
              <input id="evidence_title" name="evidence_title" required>
              <label for="evidence_summary">Evidence summary</label>
              <textarea id="evidence_summary" name="evidence_summary" rows="2"></textarea>
              <label for="packet_metadata">Packet metadata JSON</label>
              <textarea id="packet_metadata" name="packet_metadata" rows="2">{{"source": "author"}}</textarea>
            </fieldset>
            <fieldset>
              <legend>Decision point</legend>
              <label for="decision_title">Decision title</label>
              <input id="decision_title" name="decision_title" required>
              <label for="decision_prompt">Decision prompt</label>
              <textarea id="decision_prompt" name="decision_prompt" rows="2" required></textarea>
              <label for="decision_type">Decision type</label>
              <select id="decision_type" name="decision_type">
                <option value="single-choice">single-choice</option>
                <option value="free-response">free-response</option>
                <option value="evidence-selection">evidence-selection</option>
              </select>
              <label for="decision_options">Decision options JSON</label>
              <textarea id="decision_options" name="decision_options" rows="2">[{{"label": "Approve", "value": "approve"}}]</textarea>
            </fieldset>
            <button type="submit">Create case</button>
          </form>
          <section aria-labelledby="cases-list-heading">
            <h2 id="cases-list-heading">Case library</h2>
            {"<ul class='author-list'>" + "".join(items) + "</ul>" if items else empty_state("No cases", "Create the first case shell with a step, evidence packet, and decision point.")}
          </section>
        </main>
        """,
        active_path="/app/author",
    )


def _author_header(title: str) -> str:
    return f"""
      <header>
        <p class="eyebrow">Authoring workspace</p>
        <h1>{escape(title)}</h1>
      </header>
      <nav class="subnav" aria-label="Authoring tools">
        <a href="/app/author/goals">Goals</a>
        <a href="/app/author/knowledge">Knowledge graph</a>
        <a href="/app/author/prompts">Prompts</a>
        <a href="/app/author/rubrics">Rubrics</a>
        <a href="/app/author/feedback-templates">Feedback templates</a>
        <a href="/app/author/cases">Cases</a>
      </nav>
    """


def _scope_status_actor_fields(*, include_actor: bool = True) -> str:
    actor = (
        """
        <label for="authoring_actor">Authoring actor</label>
        <input id="authoring_actor" name="authoring_actor" value="author-1" required>
        """
        if include_actor
        else ""
    )
    return f"""
      <label for="ownership_scope">Ownership scope</label>
      <select id="ownership_scope" name="ownership_scope">
        <option value="personal">personal</option>
        <option value="institutional">institutional</option>
      </select>
      <label for="status">Status</label>
      <select id="status" name="status">
        <option value="draft">draft</option>
        <option value="published">published</option>
      </select>
      {actor}
    """


def _preview(preview: str) -> str:
    if not preview:
        return ""
    return (
        '<section class="preview" aria-label="Template preview">'
        f"<h2>Preview</h2><p>{escape(preview)}</p>"
        "</section>"
    )


def _notice(message: str | None, error: str | None = None) -> str:
    if error is not None:
        return f"<p role='alert' class='validation-error'>{escape(error)}</p>"
    if message is not None:
        return f"<p class='success'>{escape(message)}</p>"
    return ""


def _select(
    name: str,
    choices: tuple[str, ...],
    selected: str,
    *,
    id_prefix: str | None = None,
) -> str:
    label = name.replace("_", " ")
    field_id = f"{id_prefix}-{name}" if id_prefix is not None else name
    options = [
        f'<option value="{escape(choice)}"'
        f"{' selected' if choice == selected else ''}>{escape(choice)}</option>"
        for choice in choices
    ]
    return (
        f'<label for="{escape(field_id)}">{escape(label)}</label>'
        f'<select id="{escape(field_id)}" name="{escape(name)}">{"".join(options)}</select>'
    )


def _split_ids(value: str) -> list[str]:
    return [part.strip() for part in value.replace("\n", ",").split(",") if part.strip()]


def _optional_float(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _confidence_value(value: float | None) -> str:
    return "not recorded" if value is None else f"{value:.2f}"


def _node_hint(nodes: Sequence[KnowledgeNode]) -> str:
    if not nodes:
        return "No nodes are available in this scope."
    return ", ".join(f"{node.title} ({node.id})" for node in nodes)


def _source_hint(sources: Sequence[SourceReference]) -> str:
    if not sources:
        return "No source references are available."
    return ", ".join(
        f"{_author_source_label(source)} ({source.id}, drift {source.drift_status})"
        for source in sources
    )


def _author_source_label(source: SourceReference) -> str:
    if source.source_visibility == "local-only":
        return f"local-only source hidden; {source.hash_algorithm}={source.content_hash}"
    return source.stable_locator


def _form_dict(body: bytes) -> dict[str, str]:
    raw_form = parse_qs(body.decode(), keep_blank_values=True)
    return {key: values[-1] for key, values in raw_form.items()}


def _required_text(form: dict[str, str], key: str) -> str:
    value = _optional_text(form.get(key))
    if value is None:
        raise ValueError(f"{key} is required")
    return value


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _required_int(form: dict[str, str], key: str) -> int:
    try:
        return int(_required_text(form, key))
    except ValueError as exc:
        raise ValueError(f"{key} must be an integer") from exc


def _required_float(form: dict[str, str], key: str) -> float:
    try:
        return float(_required_text(form, key))
    except ValueError as exc:
        raise ValueError(f"{key} must be a number") from exc


def _json_object(value: str | None) -> dict[str, object]:
    text = _optional_text(value)
    if text is None:
        return {}
    parsed = loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("JSON value must be an object")
    return parsed


def _json_list(value: str | None) -> list[dict[str, object]]:
    text = _optional_text(value)
    if text is None:
        return []
    parsed = loads(text)
    if not isinstance(parsed, list) or not all(isinstance(item, dict) for item in parsed):
        raise ValueError("JSON value must be a list of objects")
    return parsed


def _csv_values(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]
