"""HTTP routes for recomputed mastery estimates."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from lms.auth.login import SettingsDep
from lms.db.session import get_session
from lms.learners.identity import CurrentUserDep, require_learner_ownership
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
def list_mastery_estimates_route(
    learner_id: str,
    session: SessionDep,
    current_user: CurrentUserDep,
    settings: SettingsDep,
) -> list[dict[str, object]]:
    """Return recomputed mastery estimates for a learner."""
    require_learner_ownership(session, user=current_user, settings=settings, learner_id=learner_id)
    return mastery_estimates_for_learner(session, learner_id)
