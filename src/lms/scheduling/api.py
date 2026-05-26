"""HTTP routes for the review queue."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from lms.db.session import get_session
from lms.scheduling.repository import list_review_queue_for_learner
from lms.scheduling.schemas import QueueStatus, ReviewQueueItemRead

router = APIRouter(prefix="/learners", tags=["scheduling"])
SessionDep = Annotated[Session, Depends(get_session)]


@router.get(
    "/{learner_id}/review-queue",
    response_model=list[ReviewQueueItemRead],
)
def list_review_queue_route(
    learner_id: str,
    session: SessionDep,
    status: Annotated[
        QueueStatus | None,
        Query(description="Filter by queue item status (default: pending)."),
    ] = "pending",
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[ReviewQueueItemRead]:
    """Return review queue items for a learner with reason codes and explanations."""
    items = list_review_queue_for_learner(
        session,
        learner_id=learner_id,
        status=status,
        limit=limit,
    )
    return [ReviewQueueItemRead.model_validate(item) for item in items]
