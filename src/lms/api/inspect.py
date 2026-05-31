"""Inspect API for debugging evidence, mastery, prompts, sources, and scheduler state."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from lms.analytics.calibration import calibration_for_learner
from lms.db.session import get_session
from lms.evidence.models import EvidenceRecord
from lms.mastery.service import mastery_estimates_for_learner
from lms.sources.models import SourceReference

try:  # Prompt support is present after the prompt-provenance opener branch lands.
    from lms.prompts.models import Prompt
except ImportError:  # pragma: no cover
    Prompt = None  # type: ignore[assignment,misc]

router = APIRouter(prefix="/inspect", tags=["inspect"])
SessionDep = Annotated[Session, Depends(get_session)]


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
    source_rows = list(
        session.scalars(
            select(SourceReference).order_by(SourceReference.captured_at.desc()).limit(25)
        )
    )
    prompt_rows: list[Any] = []
    if Prompt is not None:
        prompt_rows = list(
            session.scalars(select(Prompt).order_by(Prompt.updated_at.desc()).limit(25))
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
                "version": prompt.version,
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
        "scheduler": {"status": "placeholder", "events": []},
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
