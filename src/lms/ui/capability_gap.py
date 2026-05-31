"""Personal capability and gap-analysis surface (Surface 7).

This is the M6 learner-facing UI over the M5 capability service in
:mod:`lms.capability.api`. It is personal-scope only: it never offers
institutional targets, manager approvals, certifications, or permanent
pass/fail labels, and it speaks in cautious present-tense "current evidence"
language so an estimate reads as a snapshot rather than a verdict.
"""

from __future__ import annotations

import re
from html import escape
from typing import Annotated
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from lms.capability.repository import (
    create_capability_target,
    create_gap_analysis,
    create_maintenance_plan,
    get_capability_target,
    list_capability_estimates,
    list_capability_targets,
    list_gap_analyses,
    list_maintenance_plans,
    recompute_capability_estimate,
    serialize_capability_estimate,
    serialize_capability_target,
    serialize_gap_analysis,
    serialize_maintenance_plan,
)
from lms.capability.schemas import (
    CapabilityEstimateRecompute,
    CapabilityTargetCreate,
    GapAnalysisCreate,
    MaintenancePlanCreate,
)
from lms.competencies.models import Competency
from lms.db.session import get_session
from lms.graphs.models import KnowledgeNode
from lms.learners.models import LearningGoal
from lms.ui.shell import empty_state, render_page

router = APIRouter(tags=["learner-ui"])
SessionDep = Annotated[Session, Depends(get_session)]

CAPABILITY_PATH = "/app/learner/capability"
TARGETS_PATH = f"{CAPABILITY_PATH}/targets"
ESTIMATES_PATH = f"{CAPABILITY_PATH}/estimates"
GAP_PATH = f"{CAPABILITY_PATH}/gap-analyses"
PLAN_PATH = f"{CAPABILITY_PATH}/maintenance-plans"
REVIEW_QUEUE_PATH = "/app/learner/review"
ATTEMPT_FLOW_PATH = "/app/learner/attempts"

# Display groups for gap items. Keys match ``gap_type`` values produced by
# :func:`lms.capability.repository.create_gap_analysis`.
GAP_TYPE_GROUPS: tuple[tuple[str, str], ...] = (
    ("missing_evidence", "Missing evidence"),
    ("weak_mastery", "Weak mastery"),
    ("low_confidence_evidence", "Stale or low-confidence evidence"),
    ("support_dependence", "Support dependence"),
    ("transfer_evidence_needed", "Transfer evidence needed"),
)

_CURRENT_EVIDENCE_NOTE = (
    "These reflect your current evidence only. They are a present snapshot, not a "
    "permanent certification or a comparison with anyone else."
)


@router.get(CAPABILITY_PATH, response_class=HTMLResponse)
def capability_overview_route(
    session: SessionDep,
    learner_id: Annotated[str, Query(min_length=1, max_length=36)] = "learner-1",
) -> str:
    """Return the personal capability overview with the target-creation form."""
    return _overview_surface(session=session, learner_id=learner_id, error=None)


@router.get(f"{CAPABILITY_PATH}/targets/{{target_id}}", response_class=HTMLResponse)
def capability_target_detail_route(target_id: str, session: SessionDep) -> str:
    """Return the detail surface for one personal capability target."""
    target = _target_payload(session, target_id)
    if target is None:
        return _not_found_page()
    return _detail_surface(session=session, target=target, notice=None)


@router.post(TARGETS_PATH, response_class=HTMLResponse)
async def create_capability_target_action(request: Request, session: SessionDep) -> str:
    """Create a personal capability target from the overview form."""
    form = _parse_form((await request.body()).decode())
    learner_id = _one(form, "learner_id", "learner-1")
    try:
        payload = CapabilityTargetCreate(
            learner_id=learner_id,
            title=_one(form, "title"),
            description=_one(form, "description") or None,
            target_node_ids=_many(form, "target_node_ids"),
            target_competency_ids=_many(form, "target_competency_ids"),
            required_evidence_types=_split_tokens(_one(form, "required_evidence_types")),
            confidence_threshold=_float_or_default(
                _optional_float(_one(form, "confidence_threshold")), 0.8
            ),
        )
    except (ValidationError, ValueError):
        return _overview_surface(
            session=session,
            learner_id=learner_id,
            error=(
                "Enter a title and select at least one knowledge node or competency "
                "for this personal capability target."
            ),
        )
    try:
        target_model = create_capability_target(
            session,
            learner_id=payload.learner_id,
            title=payload.title,
            description=payload.description,
            ownership_scope=payload.ownership_scope,
            learning_goal_id=payload.learning_goal_id,
            target_node_ids=payload.target_node_ids,
            target_competency_ids=payload.target_competency_ids,
            required_evidence_types=payload.required_evidence_types,
            confidence_threshold=payload.confidence_threshold,
            status=payload.status,
        )
        session.commit()
        session.refresh(target_model)
        target = serialize_capability_target(target_model)
    except ValueError as exc:
        session.rollback()
        return _overview_surface(session=session, learner_id=learner_id, error=str(exc))
    return _detail_surface(
        session=session, target=target, notice="Saved your personal capability target."
    )


@router.post(ESTIMATES_PATH, response_class=HTMLResponse)
async def recompute_estimate_action(request: Request, session: SessionDep) -> str:
    """Recompute a current capability estimate for one target."""
    form = _parse_form((await request.body()).decode())
    target_id = _one(form, "target_id")
    try:
        payload = CapabilityEstimateRecompute(target_id=target_id)
        estimate = recompute_capability_estimate(session, target_id=payload.target_id)
        session.commit()
        session.refresh(estimate)
    except (ValidationError, ValueError) as exc:
        session.rollback()
        return _action_error(session=session, target_id=target_id, exc=exc)
    return _detail_after_action(
        session=session,
        target_id=target_id,
        notice="Recomputed your current capability estimate from the latest evidence.",
    )


@router.post(GAP_PATH, response_class=HTMLResponse)
async def create_gap_analysis_action(request: Request, session: SessionDep) -> str:
    """Generate a gap analysis from the most recent estimate."""
    form = _parse_form((await request.body()).decode())
    target_id = _one(form, "target_id")
    try:
        payload = GapAnalysisCreate(estimate_id=_one(form, "estimate_id"))
        analysis = create_gap_analysis(session, estimate_id=payload.estimate_id)
        session.commit()
        session.refresh(analysis)
        target_id = analysis.target_id
    except (ValidationError, ValueError) as exc:
        session.rollback()
        return _action_error(session=session, target_id=target_id, exc=exc)
    return _detail_after_action(
        session=session,
        target_id=target_id,
        notice="Generated a gap analysis from your current evidence.",
    )


@router.post(PLAN_PATH, response_class=HTMLResponse)
async def create_maintenance_plan_action(request: Request, session: SessionDep) -> str:
    """Create a maintenance plan with scheduled next steps from a gap analysis."""
    form = _parse_form((await request.body()).decode())
    target_id = _one(form, "target_id")
    try:
        payload = MaintenancePlanCreate(gap_analysis_id=_one(form, "gap_analysis_id"))
        plan = create_maintenance_plan(session, gap_analysis_id=payload.gap_analysis_id)
        session.commit()
        session.refresh(plan)
        target_id = plan.target_id
    except (ValidationError, ValueError) as exc:
        session.rollback()
        return _action_error(session=session, target_id=target_id, exc=exc)
    return _detail_after_action(
        session=session,
        target_id=target_id,
        notice="Created a maintenance plan with scheduled next steps.",
    )


def _overview_surface(*, session: Session, learner_id: str, error: str | None) -> str:
    targets = [
        serialize_capability_target(target)
        for target in list_capability_targets(session, learner_id=learner_id)
    ]
    if targets:
        cards = "".join(_target_card(target) for target in targets)
        target_list = f"<ul class='capability-target-list'>{cards}</ul>"
    else:
        target_list = empty_state(
            "No capability targets yet",
            "Set a personal capability target below to see your current evidence, gaps, "
            "and scheduled next steps.",
        )
    return _page(
        title="Capability",
        eyebrow="Personal capability",
        heading="Your capability targets",
        body=f"""
        {_error_notice(error)}
        <p class="scope-note">Personal scope only. {escape(_CURRENT_EVIDENCE_NOTE)}</p>
        <section aria-labelledby="targets-heading">
          <h2 id="targets-heading">Capability targets</h2>
          {target_list}
        </section>
        {_create_target_form(session=session, learner_id=learner_id)}
        """,
    )


def _detail_surface(*, session: Session, target: dict[str, object], notice: str | None) -> str:
    target_id = _s(target["id"])
    estimates = _estimate_payloads(session, target_id)
    analyses = _analysis_payloads(session, target_id)
    plans = _plan_payloads(session, target_id)
    latest_estimate = estimates[0] if estimates else None
    latest_analysis = analyses[0] if analyses else None
    latest_plan = plans[0] if plans else None
    return _page(
        title="Capability target",
        eyebrow="Personal capability",
        heading=_s(target["title"]),
        body=f"""
        {_notice_block(notice)}
        <p class="scope-note">Personal scope only. {escape(_CURRENT_EVIDENCE_NOTE)}</p>
        {_target_summary_block(session, target)}
        {_estimate_block(target_id=target_id, estimate=latest_estimate)}
        {_gap_block(target_id=target_id, estimate=latest_estimate, analysis=latest_analysis)}
        {_plan_block(analysis=latest_analysis, plan=latest_plan)}
        <p class="back-link"><a href="{CAPABILITY_PATH}?learner_id={escape(_s(target["learner_id"]))}">
          Back to all capability targets</a></p>
        """,
    )


def _detail_after_action(*, session: Session, target_id: str, notice: str) -> str:
    target = _target_payload(session, target_id)
    if target is None:
        return _not_found_page()
    return _detail_surface(session=session, target=target, notice=notice)


def _action_error(*, session: Session, target_id: str, exc: ValidationError | ValueError) -> str:
    target = _target_payload(session, target_id)
    if target is None:
        return _not_found_page()
    detail = str(exc) if isinstance(exc, ValueError) else "Check the form and try again."
    return _detail_surface_with_error(session=session, target=target, error=detail)


def _detail_surface_with_error(*, session: Session, target: dict[str, object], error: str) -> str:
    target_id = _s(target["id"])
    estimates = _estimate_payloads(session, target_id)
    analyses = _analysis_payloads(session, target_id)
    plans = _plan_payloads(session, target_id)
    return _page(
        title="Capability target",
        eyebrow="Personal capability",
        heading=_s(target["title"]),
        body=f"""
        {_error_notice(error)}
        <p class="scope-note">Personal scope only. {escape(_CURRENT_EVIDENCE_NOTE)}</p>
        {_target_summary_block(session, target)}
        {_estimate_block(target_id=target_id, estimate=estimates[0] if estimates else None)}
        {
            _gap_block(
                target_id=target_id,
                estimate=estimates[0] if estimates else None,
                analysis=analyses[0] if analyses else None,
            )
        }
        {
            _plan_block(
                analysis=analyses[0] if analyses else None,
                plan=plans[0] if plans else None,
            )
        }
        """,
    )


def _target_payload(session: Session, target_id: str) -> dict[str, object] | None:
    target = get_capability_target(session, target_id)
    return serialize_capability_target(target) if target is not None else None


def _estimate_payloads(session: Session, target_id: str) -> list[dict[str, object]]:
    return [
        serialize_capability_estimate(estimate)
        for estimate in list_capability_estimates(session, target_id=target_id)
    ]


def _analysis_payloads(session: Session, target_id: str) -> list[dict[str, object]]:
    return [
        serialize_gap_analysis(analysis)
        for analysis in list_gap_analyses(session, target_id=target_id)
    ]


def _plan_payloads(session: Session, target_id: str) -> list[dict[str, object]]:
    return [
        serialize_maintenance_plan(plan)
        for plan in list_maintenance_plans(session, target_id=target_id)
    ]


def _target_card(target: dict[str, object]) -> str:
    target_id = _s(target["id"])
    node_ids = _str_list(target.get("target_node_ids"))
    competency_ids = _str_list(target.get("target_competency_ids"))
    return (
        "<li class='capability-target'>"
        f"<a href='{TARGETS_PATH}/{escape(target_id)}'><strong>{escape(_s(target['title']))}</strong></a>"
        f"<span class='target-status'>Status: {escape(_s(target['status']))}</span>"
        f"<span class='target-scope'>Scope: {escape(_s(target['ownership_scope']))}</span>"
        f"<span class='target-counts'>{len(node_ids)} node(s), {len(competency_ids)} competency(ies)</span>"
        "</li>"
    )


def _target_summary_block(session: Session, target: dict[str, object]) -> str:
    goal_id = target.get("learning_goal_id")
    goal_line = "Not linked to a learning goal yet."
    if isinstance(goal_id, str) and goal_id:
        goal = session.get(LearningGoal, goal_id)
        goal_line = (
            f"Linked goal: {escape(goal.title)}"
            if goal is not None
            else f"Linked goal: {escape(goal_id)}"
        )
    nodes = _resolve_node_titles(session, _str_list(target.get("target_node_ids")))
    competencies = _resolve_competency_titles(
        session, _str_list(target.get("target_competency_ids"))
    )
    required = _str_list(target.get("required_evidence_types"))
    required_line = (
        ", ".join(escape(value) for value in required) if required else "none specified yet"
    )
    threshold = _as_float(target.get("confidence_threshold"))
    return f"""
        <section aria-labelledby="target-heading" class="target-summary">
          <h2 id="target-heading">Target setup</h2>
          <p class="goal-line">{goal_line}</p>
          <p>Knowledge nodes: {nodes}</p>
          <p>Competencies: {competencies}</p>
          <p>Required evidence: {required_line}</p>
          <p>Confidence threshold: <strong>{threshold:.0%}</strong></p>
        </section>
    """


def _estimate_block(*, target_id: str, estimate: dict[str, object] | None) -> str:
    recompute_form = _action_form(
        action=ESTIMATES_PATH,
        fields={"target_id": target_id},
        label="Recompute current estimate",
    )
    if estimate is None:
        return f"""
        <section aria-labelledby="estimate-heading" class="capability-estimate">
          <h2 id="estimate-heading">Current capability estimate</h2>
          {
            empty_state(
                "No current estimate yet",
                "Recompute an estimate once you have collected evidence for these nodes "
                "so you can see where your current evidence stands.",
            )
        }
          {recompute_form}
        </section>
        """
    score = _as_float(estimate.get("current_score"))
    confidence = _as_float(estimate.get("confidence"))
    breakdown = estimate.get("evidence_breakdown")
    weak_ids = _str_list(estimate.get("weak_node_ids"))
    weak_line = (
        "Weak or missing evidence right now: " + ", ".join(escape(value) for value in weak_ids)
        if weak_ids
        else "No nodes are flagged as weak or missing right now."
    )
    gap_form = _action_form(
        action=GAP_PATH,
        fields={"target_id": target_id, "estimate_id": _s(estimate["id"])},
        label="Generate gap analysis",
    )
    return f"""
        <section aria-labelledby="estimate-heading" class="capability-estimate">
          <h2 id="estimate-heading">Current capability estimate</h2>
          <p class="estimate-score">Current evidence score: <strong>{score:.0%}</strong>
            (confidence {confidence:.0%}).</p>
          <p class="estimate-commentary">{escape(_s(estimate.get("commentary", "")))}</p>
          <p class="validity-scope">{escape(_s(estimate.get("validity_scope", "")))}</p>
          <p class="weak-evidence">{weak_line}</p>
          <h3>Evidence breakdown</h3>
          {_evidence_breakdown_block(breakdown)}
          <div class="estimate-actions">
            {recompute_form}
            {gap_form}
          </div>
        </section>
    """


def _evidence_breakdown_block(breakdown: object) -> str:
    if not isinstance(breakdown, dict):
        return empty_state(
            "No evidence breakdown yet",
            "Collect evidence for these nodes to see how your current evidence breaks down.",
        )
    rows = _list_of_dicts(breakdown.get("target_node_estimates"))
    competency_rows = _list_of_dicts(breakdown.get("competency_evidence"))
    items: list[str] = []
    for row in rows:
        items.append(
            "<li class='breakdown-node'>"
            f"Node {escape(_s(row.get('knowledge_node_id', '')))}: "
            f"current evidence {_as_float(row.get('current_estimate')):.0%}, "
            f"confidence {_as_float(row.get('confidence')):.0%}, "
            f"evidence count {_as_int(row.get('evidence_count'))}. "
            f"Next evidence needed: {escape(_s(row.get('next_evidence_needed', 'more evidence')))}."
            "</li>"
        )
    for row in competency_rows:
        items.append(
            "<li class='breakdown-competency'>"
            f"Competency {escape(_s(row.get('title', row.get('competency_id', ''))))}: "
            f"weighted evidence {_as_float(row.get('weighted_score')):.0%}, "
            f"evidence count {_as_int(row.get('evidence_count'))}."
            "</li>"
        )
    if not items:
        return empty_state(
            "No evidence breakdown yet",
            "Collect evidence for these nodes to see how your current evidence breaks down.",
        )
    return f"<ul class='evidence-breakdown'>{''.join(items)}</ul>"


def _gap_block(
    *, target_id: str, estimate: dict[str, object] | None, analysis: dict[str, object] | None
) -> str:
    if analysis is None:
        detail = (
            "Recompute an estimate first, then generate a gap analysis to see what evidence "
            "is missing next."
            if estimate is None
            else "Generate a gap analysis from your current estimate to group what is missing next."
        )
        return f"""
        <section aria-labelledby="gap-heading" class="capability-gaps">
          <h2 id="gap-heading">Current gaps</h2>
          {empty_state("No gap analysis yet", detail)}
        </section>
        """
    gap_items = _list_of_dicts(analysis.get("gap_items"))
    plan_form = _action_form(
        action=PLAN_PATH,
        fields={"target_id": target_id, "gap_analysis_id": _s(analysis["id"])},
        label="Create maintenance plan",
    )
    if not gap_items:
        return f"""
        <section aria-labelledby="gap-heading" class="capability-gaps">
          <h2 id="gap-heading">Current gaps</h2>
          {
            empty_state(
                "No gaps in your current evidence",
                "Your current evidence meets this target. Keep practising to maintain it.",
            )
        }
          {plan_form}
        </section>
        """
    severity = escape(_s(analysis.get("severity", "")))
    return f"""
        <section aria-labelledby="gap-heading" class="capability-gaps">
          <h2 id="gap-heading">Current gaps</h2>
          <p class="gap-severity">Overall severity right now: <strong>{severity}</strong>.</p>
          {_grouped_gap_items(gap_items)}
          {plan_form}
        </section>
    """


def _grouped_gap_items(gap_items: list[dict[str, object]]) -> str:
    sections: list[str] = []
    for gap_type, label in GAP_TYPE_GROUPS:
        group = [item for item in gap_items if _s(item.get("gap_type")) == gap_type]
        if not group:
            continue
        rows = "".join(
            "<li class='gap-item'>"
            f"<span class='gap-target'>{_gap_target_label(item)}</span>"
            f"<span class='gap-rationale'>{escape(_s(item.get('rationale', '')))}</span>"
            f"<span class='gap-action'>Suggested next step: {escape(_s(item.get('recommended_action_type', '')))}</span>"
            "</li>"
            for item in group
        )
        sections.append(
            f"<div class='gap-group'><h3>{escape(label)}</h3><ul class='gap-list'>{rows}</ul></div>"
        )
    return "".join(sections)


def _gap_target_label(item: dict[str, object]) -> str:
    node_id = item.get("knowledge_node_id")
    if isinstance(node_id, str) and node_id:
        return f"Node {escape(node_id)}"
    competency_id = item.get("competency_id")
    if isinstance(competency_id, str) and competency_id:
        return f"Competency {escape(competency_id)}"
    return "Target"


def _plan_block(*, analysis: dict[str, object] | None, plan: dict[str, object] | None) -> str:
    if plan is None:
        return f"""
        <section aria-labelledby="plan-heading" class="maintenance-plan">
          <h2 id="plan-heading">Maintenance plan</h2>
          {
            empty_state(
                "No maintenance-plan steps yet",
                "Create a maintenance plan from your gap analysis to schedule your next steps."
                if analysis is not None
                else "Generate a gap analysis first, then create a maintenance plan of next steps.",
            )
        }
        </section>
        """
    steps = _list_of_dicts(plan.get("plan_steps"))
    if not steps:
        body = empty_state(
            "No maintenance-plan steps yet",
            "This plan has no scheduled steps because your current evidence has no open gaps.",
        )
    else:
        body = f"<ol class='plan-steps'>{''.join(_plan_step(step) for step in steps)}</ol>"
    return f"""
        <section aria-labelledby="plan-heading" class="maintenance-plan">
          <h2 id="plan-heading">Maintenance plan</h2>
          <p class="plan-rationale">{escape(_s(plan.get("rationale", "")))}</p>
          {body}
        </section>
    """


def _plan_step(step: dict[str, object]) -> str:
    number = _as_int(step.get("step_number"))
    rationale = escape(_s(step.get("rationale", "")))
    action_type = escape(_s(step.get("action_type", "")))
    node_id = step.get("knowledge_node_id")
    scheduled = isinstance(step.get("review_schedule_id"), str) and bool(
        step.get("review_schedule_id")
    )
    links = ""
    if isinstance(node_id, str) and node_id:
        links = (
            '<span class="step-links">'
            f'<a href="{REVIEW_QUEUE_PATH}">Open review queue</a> · '
            f'<a href="{ATTEMPT_FLOW_PATH}">Start an attempt</a>'
            "</span>"
        )
    schedule_note = (
        "<span class='step-scheduled'>Scheduled in your review queue.</span>"
        if scheduled
        else "<span class='step-scheduled'>Not yet scheduled.</span>"
    )
    return (
        "<li class='plan-step'>"
        f"<strong>Step {number}:</strong> {rationale} "
        f"<span class='step-action'>({action_type})</span> "
        f"{schedule_note} {links}"
        "</li>"
    )


def _create_target_form(*, session: Session, learner_id: str) -> str:
    nodes = list(
        session.scalars(
            select(KnowledgeNode)
            .where(KnowledgeNode.ownership_scope == "personal")
            .order_by(KnowledgeNode.title, KnowledgeNode.id)
        )
    )
    competencies = list(
        session.scalars(
            select(Competency)
            .where(Competency.ownership_scope == "personal")
            .order_by(Competency.title, Competency.id)
        )
    )
    if not nodes and not competencies:
        return f"""
        <section aria-labelledby="create-heading" class="create-target">
          <h2 id="create-heading">Set a capability target</h2>
          {
            empty_state(
                "No personal knowledge nodes or competencies yet",
                "Author personal knowledge nodes or competencies first, then return here to set "
                "a capability target over them.",
            )
        }
        </section>
        """
    node_checkboxes = "".join(
        "<label class='check'>"
        f"<input type='checkbox' name='target_node_ids' value='{escape(node.id)}'> "
        f"{escape(node.title)}"
        "</label>"
        for node in nodes
    )
    competency_checkboxes = "".join(
        "<label class='check'>"
        f"<input type='checkbox' name='target_competency_ids' value='{escape(competency.id)}'> "
        f"{escape(competency.title)}"
        "</label>"
        for competency in competencies
    )
    node_section = (
        f"<fieldset><legend>Knowledge nodes</legend>{node_checkboxes}</fieldset>" if nodes else ""
    )
    competency_section = (
        f"<fieldset><legend>Competencies</legend>{competency_checkboxes}</fieldset>"
        if competencies
        else ""
    )
    return f"""
        <section aria-labelledby="create-heading" class="create-target">
          <h2 id="create-heading">Set a capability target</h2>
          <p>Targets are personal: they track your own current evidence, not an
            institution-wide standard.</p>
          <form method="post" action="{TARGETS_PATH}">
            <input type="hidden" name="learner_id" value="{escape(learner_id)}">
            <label for="title">Target title</label>
            <input type="text" id="title" name="title" required maxlength="255">
            <label for="description">Description (optional)</label>
            <textarea id="description" name="description" rows="2"></textarea>
            {node_section}
            {competency_section}
            <label for="required_evidence_types">Required evidence types (comma separated)</label>
            <input type="text" id="required_evidence_types" name="required_evidence_types"
              placeholder="rubric-score, transfer-case">
            <label for="confidence_threshold">Confidence threshold</label>
            <input type="number" id="confidence_threshold" name="confidence_threshold"
              min="0" max="1" step="0.05" value="0.8">
            <button type="submit">Save capability target</button>
          </form>
        </section>
    """


def _action_form(*, action: str, fields: dict[str, str], label: str) -> str:
    hidden = "".join(
        f"<input type='hidden' name='{escape(key)}' value='{escape(value)}'>"
        for key, value in fields.items()
    )
    return (
        f"<form method='post' action='{action}' class='inline-action'>"
        f"{hidden}<button type='submit'>{escape(label)}</button></form>"
    )


def _resolve_node_titles(session: Session, node_ids: list[str]) -> str:
    if not node_ids:
        return "none linked yet"
    nodes = list(session.scalars(select(KnowledgeNode).where(KnowledgeNode.id.in_(node_ids))))
    titles_by_id = {node.id: node.title for node in nodes}
    labels = [escape(titles_by_id.get(node_id, node_id)) for node_id in node_ids]
    return ", ".join(labels)


def _resolve_competency_titles(session: Session, competency_ids: list[str]) -> str:
    if not competency_ids:
        return "none linked yet"
    competencies = list(
        session.scalars(select(Competency).where(Competency.id.in_(competency_ids)))
    )
    titles_by_id = {competency.id: competency.title for competency in competencies}
    labels = [
        escape(titles_by_id.get(competency_id, competency_id)) for competency_id in competency_ids
    ]
    return ", ".join(labels)


def _page(*, title: str, eyebrow: str, heading: str, body: str) -> str:
    return render_page(
        title,
        f"""
        <main class="surface capability-surface">
          <header>
            <p class="eyebrow">{escape(eyebrow)}</p>
            <h1>{escape(heading)}</h1>
          </header>
          {body}
        </main>
        """,
        active_path="/app/learner",
    )


def _not_found_page() -> str:
    return _page(
        title="Capability target",
        eyebrow="Personal capability",
        heading="Capability target",
        body=empty_state(
            "Capability target not found",
            "This personal capability target does not exist. Return to your capability "
            f"targets to set one. <a href='{CAPABILITY_PATH}'>Back to capability targets</a>.",
        ),
    )


def _error_notice(error: str | None) -> str:
    if not error:
        return ""
    return f"<p role='alert' class='validation-error'>{escape(error)}</p>"


def _notice_block(notice: str | None) -> str:
    if not notice:
        return ""
    return f"<p role='status' class='notice'>{escape(notice)}</p>"


def _parse_form(body: str) -> dict[str, list[str]]:
    return parse_qs(body, keep_blank_values=True)


def _one(form: dict[str, list[str]], key: str, default: str = "") -> str:
    values = form.get(key)
    return values[-1] if values else default


def _many(form: dict[str, list[str]], key: str) -> list[str]:
    return [value for value in form.get(key, []) if value]


def _split_tokens(raw: str) -> list[str]:
    return [token.strip() for token in re.split(r"[,\n]", raw) if token.strip()]


def _optional_float(raw: str) -> float | None:
    text = raw.strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _float_or_default(value: float | None, default: float) -> float:
    return default if value is None else value


def _s(value: object) -> str:
    return "" if value is None else str(value)


def _str_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _as_float(value: object) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return 0.0
    return 0.0


def _as_int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float | str):
        try:
            return int(float(value))
        except (TypeError, ValueError, OverflowError):
            # OverflowError guards non-finite strings ("inf"/"-inf"); NaN raises ValueError.
            return 0
    return 0


def _list_of_dicts(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]
