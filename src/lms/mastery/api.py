"""HTTP routes for recomputed mastery estimates."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from lms.db.session import get_session
from lms.mastery.service import mastery_estimates_for_learner

router = APIRouter(prefix="/learners", tags=["mastery"])
SessionDep = Annotated[Session, Depends(get_session)]


class MasteryEstimateRead(BaseModel):
    """Serializable recomputed mastery estimate."""

    learner_id: str
    knowledge_node_id: str
    current_estimate: float
    confidence: float
    evidence_count: int
    last_evidence_id: str
    last_evidence_at: datetime
    estimator_version: str
    model_attribution: str
    generated_at: datetime


@router.get("/{learner_id}/mastery-estimates", response_model=list[MasteryEstimateRead])
def list_mastery_estimates_route(learner_id: str, session: SessionDep) -> list[dict[str, object]]:
    """Return recomputed mastery estimates for a learner."""
    return mastery_estimates_for_learner(session, learner_id)
