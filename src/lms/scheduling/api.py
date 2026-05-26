"""HTTP routes for the review queue."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from lms.db.session import get_session
from lms.scheduling.repository import (
    count_review_queue_for_learner,
    create_remediation_trigger,
    list_remediation_triggers,
    list_review_policies,
    list_review_queue_for_learner,
    list_review_schedules,
    list_scheduler_decisions,
)
from lms.scheduling.schemas import (
    QueueStatus,
    ReasonCode,
    RemediationTriggerCreate,
    RemediationTriggerRead,
    ReviewPolicyRead,
    ReviewQueueItemRead,
    ReviewQueueResponse,
    ReviewScheduleRead,
    SchedulerDecisionRead,
    ScheduleState,
)
from lms.scheduling.service import DEFAULT_DAILY_CAP, SchedulerSettings, get_review_queue_overview

router = APIRouter(tags=["scheduling"])
SessionDep = Annotated[Session, Depends(get_session)]


@router.get(
    "/learners/{learner_id}/review-queue",
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
    ] = DEFAULT_DAILY_CAP,
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
    backlog_total = count_review_queue_for_learner(
        session,
        learner_id=learner_id,
        status=status,
    )
    return ReviewQueueResponse(
        learner_id=learner_id,
        daily_cap=min(daily_cap, limit),
        backlog_total=backlog_total,
        returned_count=len(items),
        backlog_note=(
            f"{backlog_total} item(s) for this filter; backlog totals are informational, "
            "not an obligation score."
        ),
        items=items,
    )


@router.post(
    "/remediation-triggers",
    response_model=RemediationTriggerRead,
    status_code=status.HTTP_201_CREATED,
)
def create_remediation_trigger_route(
    payload: RemediationTriggerCreate,
    session: SessionDep,
) -> RemediationTriggerRead:
    """Create a deterministic remediation trigger."""
    try:
        trigger = create_remediation_trigger(session, **payload.model_dump())
        session.commit()
        session.refresh(trigger)
    except ValueError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return RemediationTriggerRead.model_validate(trigger)


@router.get("/remediation-triggers", response_model=list[RemediationTriggerRead])
def list_remediation_triggers_route(
    session: SessionDep,
    knowledge_node_id: Annotated[str | None, Query(min_length=1, max_length=36)] = None,
    trigger_type: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
    active_only: bool = True,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[RemediationTriggerRead]:
    """Return remediation triggers with common filters."""
    triggers = list_remediation_triggers(
        session,
        knowledge_node_id=knowledge_node_id,
        trigger_type=trigger_type,
        active_only=active_only,
        limit=limit,
    )
    return [RemediationTriggerRead.model_validate(trigger) for trigger in triggers]


@router.get("/review-policies", response_model=list[ReviewPolicyRead])
def list_review_policies_route(
    session: SessionDep,
    reason_code: Annotated[
        ReasonCode | None,
        Query(description="Filter policies by queue/schedule reason code."),
    ] = None,
    active_only: Annotated[bool, Query(description="Return only active policies.")] = True,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[ReviewPolicyRead]:
    """Return durable scheduler policy records."""
    return [
        ReviewPolicyRead.model_validate(policy)
        for policy in list_review_policies(
            session,
            reason_code=reason_code,
            active_only=active_only,
            limit=limit,
        )
    ]


@router.get("/review-schedules", response_model=list[ReviewScheduleRead])
def list_review_schedules_route(
    session: SessionDep,
    learner_id: Annotated[str | None, Query(description="Filter by learner id.")] = None,
    knowledge_node_id: Annotated[
        str | None,
        Query(description="Filter by knowledge node id."),
    ] = None,
    schedule_state: Annotated[
        ScheduleState | None,
        Query(description="Filter by durable schedule state."),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[ReviewScheduleRead]:
    """Return durable review schedule records."""
    return [
        ReviewScheduleRead.model_validate(schedule)
        for schedule in list_review_schedules(
            session,
            learner_id=learner_id,
            knowledge_node_id=knowledge_node_id,
            schedule_state=schedule_state,
            limit=limit,
        )
    ]


@router.get("/scheduler-decisions", response_model=list[SchedulerDecisionRead])
def list_scheduler_decisions_route(
    session: SessionDep,
    learner_id: Annotated[str | None, Query(description="Filter by learner id.")] = None,
    knowledge_node_id: Annotated[
        str | None,
        Query(description="Filter by knowledge node id."),
    ] = None,
    reason_code: Annotated[
        ReasonCode | None,
        Query(description="Filter decisions by emitted reason code."),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[SchedulerDecisionRead]:
    """Return explainable scheduler decisions."""
    return [
        SchedulerDecisionRead.model_validate(decision)
        for decision in list_scheduler_decisions(
            session,
            learner_id=learner_id,
            knowledge_node_id=knowledge_node_id,
            reason_code=reason_code,
            limit=limit,
        )
    ]
