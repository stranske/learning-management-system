"""Inspect API for debugging evidence, mastery, prompts, sources, and scheduler state."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from lms.analytics.calibration import calibration_for_learner
from lms.db.session import get_session
from lms.evidence.models import EvidenceRecord
from lms.graphs.models import KnowledgeNode
from lms.mastery.service import mastery_estimates_for_learner
from lms.scheduling.models import ReviewQueueItem, SchedulerDecision
from lms.sources.models import SourceReference

try:  # Prompt support is present after the prompt-provenance opener branch lands.
    from lms.prompts.models import Prompt, prompt_source_references
except ImportError:  # pragma: no cover
    Prompt = None  # type: ignore[assignment,misc]
    prompt_source_references = None  # type: ignore[assignment]

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
                ReviewQueueItem.due_at.asc(),
                ReviewQueueItem.priority.desc(),
                ReviewQueueItem.created_at.desc(),
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
    ownership_scope: Annotated[str, Query(pattern="^(personal|institutional)$")] = "personal",
) -> dict[str, Any]:
    """Return a sparse-data-friendly Inspect overview for one learner."""
    evidence = list(
        session.scalars(
            select(EvidenceRecord)
            .where(EvidenceRecord.learner_id == learner_id)
            .order_by(EvidenceRecord.observed_at.desc())
            .limit(25)
        )
    )
    source_rows: list[SourceReference] = []
    prompt_rows: list[Any] = []
    if Prompt is not None:
        prompt_rows = list(
            session.scalars(
                select(Prompt)
                .options(selectinload(Prompt.versions))
                .join(KnowledgeNode, KnowledgeNode.id == Prompt.target_node_id)
                .where(KnowledgeNode.ownership_scope == ownership_scope)
                .order_by(Prompt.updated_at.desc())
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
        "mastery": mastery_estimates_for_learner(session, learner_id),
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
        "calibration": calibration_for_learner(session, learner_id).as_dict(),
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
    knowledge_node_id: Annotated[str | None, Query()] = None,
) -> dict[str, Any]:
    """Return confidence-vs-accuracy calibration for one learner.

    Surfaces the metacognitive-calibration analytics: per confidence bucket,
    the observed accuracy and median response time, plus an ``overconfident``
    flag when high confidence is paired with low accuracy.
    """
    return calibration_for_learner(
        session, learner_id, knowledge_node_id=knowledge_node_id
    ).as_dict()


@router.get("", response_class=HTMLResponse)
def inspect_shell_route() -> str:
    """Return a minimal mobile-friendly Inspect shell."""
    return (
        "<!doctype html><meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>LMS Inspect</title><style>body{font-family:system-ui;margin:1rem;}"
        "nav{display:flex;gap:.5rem;flex-wrap:wrap}section{margin-block:1rem}</style>"
        "<h1>Inspect</h1><nav><a>Evidence</a><a>Mastery</a><a>Prompts</a>"
        "<a>Sources</a><a>Scheduler</a></nav><section>Use the JSON overview endpoint for data.</section>"
    )
