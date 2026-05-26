"""HTTP routes for the review queue."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from lms.db.session import get_session
from lms.scheduling.repository import list_review_queue_for_learner
from lms.scheduling.schemas import QueueStatus, ReviewQueueItemRead, ReviewQueueResponse
from lms.scheduling.service import SchedulerSettings, get_review_queue_overview

router = APIRouter(prefix="/learners", tags=["scheduling"])
SessionDep = Annotated[Session, Depends(get_session)]


@router.get(
    "/{learner_id}/review-queue",
    response_model=ReviewQueueResponse,
)
def list_review_queue_route(
    learner_id: str,
    session: SessionDep,
    status: Annotated[
        QueueStatus | None,
        Query(description="Filter by queue item status (default: pending)."),
    ] = "pending",
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    daily_cap: Annotated[
        int,
        Query(
            ge=1,
            le=100,
            description="Maximum pending items to return for today's review load.",
        ),
    ] = 25,
) -> ReviewQueueResponse:
    """Return review queue items with reason codes, explanations, and backlog context."""
    if status == "pending":
        overview = get_review_queue_overview(
            session,
            learner_id=learner_id,
            settings=SchedulerSettings(daily_cap=min(daily_cap, limit)),
        )
        items = [ReviewQueueItemRead.model_validate(item) for item in overview.items]
        return ReviewQueueResponse(
            learner_id=learner_id,
            daily_cap=overview.daily_cap,
            backlog_total=overview.backlog_total,
            returned_count=len(items),
            backlog_note=overview.backlog_note,
            items=items,
        )

    items_raw = list_review_queue_for_learner(
        session,
        learner_id=learner_id,
        status=status,
        limit=limit,
    )
    items = [ReviewQueueItemRead.model_validate(item) for item in items_raw]
    return ReviewQueueResponse(
        learner_id=learner_id,
        daily_cap=min(daily_cap, limit),
        backlog_total=len(items),
        returned_count=len(items),
        backlog_note=(
            f"{len(items)} item(s) for this filter; backlog totals are informational, "
            "not an obligation score."
        ),
        items=items,
    )
