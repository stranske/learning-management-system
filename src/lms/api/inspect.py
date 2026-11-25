"""Inspect API for debugging evidence, mastery, prompts, sources, and scheduler state."""

from __future__ import annotations

from html import escape
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from lms.analytics.calibration import calibration_for_learner
from lms.auth.login import SettingsDep
from lms.db.session import get_session
from lms.evidence.models import EvidenceRecord
from lms.graphs.models import KnowledgeNode
from lms.graphs.schemas import OwnershipScope
from lms.learners.identity import CurrentUserDep, require_learner_ownership, resolve_learner_id
from lms.learners.repository import get_or_create_learner_for_user, list_learners_for_user
from lms.mastery.service import mastery_estimates_for_learner
from lms.scheduling.models import ReviewQueueItem, SchedulerDecision
from lms.sources.models import SourceReference

try:  # Prompt support is present after the prompt-provenance opener branch lands.
    from lms.prompts.models import Prompt, PromptVersion, prompt_source_references
    from lms.prompts.repository import prompt_drift_status
except ImportError:  # pragma: no cover
    Prompt = None  # type: ignore[assignment,misc]
    PromptVersion = None  # type: ignore[assignment,misc]
    prompt_source_references = None  # type: ignore[assignment]
    prompt_drift_status = None  # type: ignore[assignment]

router = APIRouter(prefix="/inspect", tags=["inspect"])
SessionDep = Annotated[Session, Depends(get_session)]


def _scheduler_panel(
    session: Session,
    *,
    learner_id: str,
    ownership_scope: str,
) -> dict[str, Any]:
    scoped_node_exists = (
        select(KnowledgeNode.id)
        .where(
            KnowledgeNode.id == ReviewQueueItem.knowledge_node_id,
            KnowledgeNode.ownership_scope == ownership_scope,
        )
        .exists()
    )
    node_exists = (
        select(KnowledgeNode.id)
        .where(KnowledgeNode.id == ReviewQueueItem.knowledge_node_id)
        .exists()
    )
    queue_items = list(
        session.scalars(
            select(ReviewQueueItem)
            .where(
                ReviewQueueItem.learner_id == learner_id,
                scoped_node_exists | ~node_exists,
            )
            .order_by(
                ReviewQueueItem.created_at.desc(),
                ReviewQueueItem.due_at.asc(),
                ReviewQueueItem.priority.desc(),
                ReviewQueueItem.id.desc(),
            )
            .limit(10)
        )
    )
    decisions = list(
        session.scalars(
            select(SchedulerDecision)
            .where(
                SchedulerDecision.learner_id == learner_id,
                SchedulerDecision.ownership_scope == ownership_scope,
            )
            .order_by(SchedulerDecision.created_at.desc(), SchedulerDecision.id)
            .limit(10)
        )
    )

    events = [
        {
            "id": item.id,
            "knowledge_node_id": item.knowledge_node_id,
            "reason_code": item.reason_code,
            "reason_explanation": item.reason_explanation,
            "due_at": item.due_at,
            "priority": item.priority,
            "status": item.status,
            "decision_log": item.decision_log,
        }
        for item in queue_items
    ]
    decision_rows = [
        {
            "id": decision.id,
            "knowledge_node_id": decision.knowledge_node_id,
            "reason_code": decision.reason_code,
            "decision_rationale": decision.decision_rationale,
            "policy_version": decision.policy_version,
            "ownership_scope": decision.ownership_scope,
            "support_level": decision.support_level,
            "decision_log": decision.decision_log,
            "created_at": decision.created_at,
        }
        for decision in decisions
    ]
    return {
        "status": "ready" if events or decision_rows else "empty",
        "ownership_scope": ownership_scope,
        "events": events,
        "decisions": decision_rows,
    }


@router.get("/learners/{learner_id}/overview")
def learner_overview_route(
    learner_id: str,
    session: SessionDep,
    current_user: CurrentUserDep,
    settings: SettingsDep,
    ownership_scope: Annotated[str, Query(pattern="^(personal|institutional)$")] = "personal",
) -> dict[str, Any]:
    """Return a sparse-data-friendly Inspect overview for one learner."""
    require_learner_ownership(session, user=current_user, settings=settings, learner_id=learner_id)
    evidence = list(
        session.scalars(
            select(EvidenceRecord)
            .join(KnowledgeNode, KnowledgeNode.id == EvidenceRecord.knowledge_node_id)
            .where(
                EvidenceRecord.learner_id == learner_id,
                KnowledgeNode.ownership_scope == ownership_scope,
            )
            .order_by(EvidenceRecord.observed_at.desc(), EvidenceRecord.id)
            .limit(25)
        )
    )
    source_rows: list[SourceReference] = []
    prompt_rows: list[Any] = []
    if Prompt is not None:
        prompt_rows = list(
            session.scalars(
                select(Prompt)
                .options(
                    selectinload(Prompt.source_references),
                    selectinload(Prompt.drift_acknowledgements),
                    selectinload(Prompt.versions).selectinload(PromptVersion.source_snapshots),
                )
                .join(KnowledgeNode, KnowledgeNode.id == Prompt.target_node_id)
                .where(KnowledgeNode.ownership_scope == ownership_scope)
                .order_by(Prompt.updated_at.desc(), Prompt.id)
                .limit(25)
            )
        )
        scoped_source_ids = (
            select(prompt_source_references.c.source_reference_id)
            .select_from(prompt_source_references)
            .join(Prompt, Prompt.id == prompt_source_references.c.prompt_id)
            .join(KnowledgeNode, KnowledgeNode.id == Prompt.target_node_id)
            .where(KnowledgeNode.ownership_scope == ownership_scope)
        )
        source_has_prompt = (
            select(prompt_source_references.c.source_reference_id)
            .where(prompt_source_references.c.source_reference_id == SourceReference.id)
            .exists()
        )
        source_rows = list(
            session.scalars(
                select(SourceReference)
                .where(SourceReference.id.in_(scoped_source_ids) | ~source_has_prompt)
                .order_by(SourceReference.captured_at.desc())
                .limit(25)
            )
        )
    else:
        source_rows = list(
            session.scalars(
                select(SourceReference).order_by(SourceReference.captured_at.desc()).limit(25)
            )
        )

    return {
        "learner_id": learner_id,
        "ownership_scope": ownership_scope,
        "mastery": mastery_estimates_for_learner(session, learner_id, scope=ownership_scope),
        "recent_evidence": [
            {
                "id": record.id,
                "knowledge_node_id": record.knowledge_node_id,
                "evidence_kind": record.evidence_kind,
                "normalized_score": record.normalized_score,
                "recorded_at": record.observed_at,
            }
            for record in evidence
        ],
        "prompt_provenance": [
            {
                "id": prompt.id,
                "status": prompt.status,
                "version": (prompt.versions[-1].version_number if prompt.versions else None),
                "authoring_method": prompt.authoring_method,
                "reviewing_actor": prompt.reviewing_actor,
                "drift_status": (
                    prompt_drift_status(prompt) if prompt_drift_status is not None else "current"
                ),
            }
            for prompt in prompt_rows
        ],
        "source_drift": [
            {
                "id": source.id,
                "source_type": source.source_type,
                "drift_status": source.drift_status,
                "source_visibility": source.source_visibility,
            }
            for source in source_rows
        ],
        "calibration": calibration_for_learner(
            session, learner_id, scope=ownership_scope
        ).as_dict(),
        "scheduler": _scheduler_panel(
            session,
            learner_id=learner_id,
            ownership_scope=ownership_scope,
        ),
    }


@router.get("/learners/{learner_id}/calibration")
def learner_calibration_route(
    learner_id: str,
    session: SessionDep,
    current_user: CurrentUserDep,
    settings: SettingsDep,
    knowledge_node_id: Annotated[str | None, Query()] = None,
    ownership_scope: Annotated[OwnershipScope, Query()] = "personal",
) -> dict[str, Any]:
    """Return confidence-vs-accuracy calibration for one learner.

    Surfaces the metacognitive-calibration analytics: per confidence bucket,
    the observed accuracy and median response time, plus an ``overconfident``
    flag when high confidence is paired with low accuracy.
    """
    require_learner_ownership(session, user=current_user, settings=settings, learner_id=learner_id)
    return calibration_for_learner(
        session, learner_id, scope=ownership_scope, knowledge_node_id=knowledge_node_id
    ).as_dict()


def _inspect_panel_summary(overview: dict[str, Any]) -> dict[str, str]:
    """Return one-line summaries for each Inspect panel from overview JSON."""
    evidence = overview.get("recent_evidence") or []
    mastery = overview.get("mastery") or []
    prompts = overview.get("prompt_provenance") or []
    sources = overview.get("source_drift") or []
    scheduler = overview.get("scheduler") or {}
    scheduler_events = scheduler.get("events") or []
    scheduler_decisions = scheduler.get("decisions") or []

    if evidence:
        latest = evidence[0]
        evidence_text = (
            f"{len(evidence)} record(s); latest node {latest.get('knowledge_node_id')} "
            f"score {latest.get('normalized_score')}"
        )
    else:
        evidence_text = "No recent evidence."

    if mastery:
        top = max(mastery, key=lambda item: float(item.get("confidence") or 0.0))
        evidence_text_mastery = (
            f"{len(mastery)} estimate(s); top confidence {top.get('confidence')} "
            f"on {top.get('knowledge_node_id')}"
        )
    else:
        evidence_text_mastery = "No mastery estimates."

    if prompts:
        latest_prompt = prompts[0]
        prompt_text = (
            f"{len(prompts)} prompt(s); latest {latest_prompt.get('id')} "
            f"status {latest_prompt.get('status')}"
        )
    else:
        prompt_text = "No prompt provenance."

    if sources:
        latest_source = sources[0]
        source_text = f"{len(sources)} source(s); latest drift {latest_source.get('drift_status')}"
    else:
        source_text = "No source drift rows."

    scheduler_text = (
        f"Status {scheduler.get('status', 'unknown')}; "
        f"{len(scheduler_events)} queue event(s), {len(scheduler_decisions)} decision(s)"
    )
    return {
        "evidence": evidence_text,
        "mastery": evidence_text_mastery,
        "prompts": prompt_text,
        "sources": source_text,
        "scheduler": scheduler_text,
    }


def _render_inspect_shell(
    *,
    learners: list[Any],
    selected_learner_id: str,
    overview: dict[str, Any],
    ownership_scope: str,
) -> str:
    """Render the mobile-friendly Inspect HTML shell."""
    summaries = _inspect_panel_summary(overview)
    scope_qs = escape(ownership_scope)
    overview_href = (
        f"/inspect/learners/{escape(selected_learner_id)}/overview" f"?ownership_scope={scope_qs}"
    )
    learner_links = []
    for learner in learners:
        label = escape(getattr(learner, "display_name", None) or learner.id)
        learner_id = escape(learner.id)
        selected_attr = ' aria-current="page"' if learner.id == selected_learner_id else ""
        learner_links.append(
            f"<a href='/inspect?learner_id={learner_id}&ownership_scope={scope_qs}'"
            f"{selected_attr}>{label}</a>"
        )
    if not learner_links:
        learner_links.append(f"<span>{escape(selected_learner_id)}</span>")

    sections = "".join(
        f"<section id='{panel}'><h2>{escape(panel.title())}</h2>"
        f"<p>{escape(summaries[panel])}</p></section>"
        for panel in ("evidence", "mastery", "prompts", "sources", "scheduler")
    )
    return (
        "<!doctype html><meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>LMS Inspect</title><style>body{font-family:system-ui;margin:1rem;}"
        "nav{display:flex;gap:.5rem;flex-wrap:wrap}section{margin-block:1rem}</style>"
        "<h1>Inspect</h1>"
        f"<nav aria-label='Learners'>{''.join(learner_links)}</nav>"
        "<nav aria-label='Panels'>"
        "<a href='#evidence'>Evidence</a><a href='#mastery'>Mastery</a>"
        "<a href='#prompts'>Prompts</a><a href='#sources'>Sources</a>"
        f"<a href='#scheduler'>Scheduler</a>"
        f"<a href='{overview_href}'>Overview JSON</a></nav>"
        f"{sections}"
    )


@router.get("", response_class=HTMLResponse)
def inspect_shell_route(
    session: SessionDep,
    current_user: CurrentUserDep,
    settings: SettingsDep,
    learner_id: Annotated[str | None, Query(min_length=1, max_length=36)] = None,
    ownership_scope: Annotated[str, Query(pattern="^(personal|institutional)$")] = "personal",
) -> str:
    """Return a minimal mobile-friendly Inspect shell."""
    learners = list_learners_for_user(session, user_id=current_user.id)
    if not learners:
        learner, created = get_or_create_learner_for_user(
            session,
            user_id=current_user.id,
            display_name=current_user.display_name or current_user.username,
        )
        if created:
            session.commit()
        learners = [learner]
    selected_learner_id = resolve_learner_id(
        session,
        user=current_user,
        settings=settings,
        requested=learner_id or learners[0].id,
    )
    require_learner_ownership(
        session, user=current_user, settings=settings, learner_id=selected_learner_id
    )
    overview = learner_overview_route(
        selected_learner_id,
        session,
        current_user,
        settings,
        ownership_scope,
    )
    return _render_inspect_shell(
        learners=learners,
        selected_learner_id=selected_learner_id,
        overview=overview,
        ownership_scope=ownership_scope,
    )
