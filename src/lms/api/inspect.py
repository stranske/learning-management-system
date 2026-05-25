"""Inspect API for debugging evidence, mastery, prompts, sources, and scheduler state."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from lms.db.session import get_session
from lms.evidence.models import EvidenceRecord
from lms.mastery.service import mastery_estimates_for_learner
from lms.sources.models import SourceReference


def _load_prompt_model() -> Any | None:
    """Load prompt model only when the local prompts module exists."""
    prompts_models = Path(__file__).resolve().parents[1] / "prompts" / "models.py"
    if not prompts_models.exists():
        return None
    module = import_module("lms.prompts.models")
    return getattr(module, "Prompt", None)


Prompt = _load_prompt_model()

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
            .order_by(EvidenceRecord.recorded_at.desc())
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
                "recorded_at": record.recorded_at,
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
        "scheduler": {"status": "placeholder", "events": []},
    }


@router.get("")
def inspect_shell_route() -> str:
    """Return a minimal mobile-friendly Inspect shell."""
    return (
        "<!doctype html><meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>LMS Inspect</title><style>body{font-family:system-ui;margin:1rem;}"
        "nav{display:flex;gap:.5rem;flex-wrap:wrap}section{margin-block:1rem}</style>"
        "<h1>Inspect</h1><nav><a>Evidence</a><a>Mastery</a><a>Prompts</a>"
        "<a>Sources</a><a>Scheduler</a></nav><section>Use the JSON overview endpoint for data.</section>"
    )
