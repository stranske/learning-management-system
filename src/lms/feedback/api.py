"""HTTP routes for durable feedback records and next actions."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from lms.db.session import get_session
from lms.evidence.models import Attempt, EvidenceRecord
from lms.feedback.repository import (
    create_feedback_action,
    create_feedback_record,
    get_feedback_action,
    get_feedback_record,
    list_feedback_actions,
    list_feedback_records,
)
from lms.feedback.schemas import (
    FeedbackActionCreate,
    FeedbackActionRead,
    FeedbackRecordCreate,
    FeedbackRecordRead,
)

router = APIRouter(tags=["feedback"])
SessionDep = Annotated[Session, Depends(get_session)]


@router.post("/feedback", response_model=FeedbackRecordRead, status_code=status.HTTP_201_CREATED)
def create_feedback_route(payload: FeedbackRecordCreate, session: SessionDep) -> FeedbackRecordRead:
    """Create a durable feedback record."""
    data = payload.model_dump()
    if data.get("attempt_id") is not None and session.get(Attempt, data["attempt_id"]) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Referenced attempt not found.",
        )
    if (
        data.get("evidence_record_id") is not None
        and session.get(EvidenceRecord, data["evidence_record_id"]) is None
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Referenced evidence record not found.",
        )
    record = create_feedback_record(session, **data)
    session.commit()
    session.refresh(record)
    return FeedbackRecordRead.model_validate(record)


@router.get("/feedback", response_model=list[FeedbackRecordRead])
def list_feedback_route(
    session: SessionDep,
    learner_id: Annotated[str | None, Query(min_length=1, max_length=36)] = None,
    attempt_id: Annotated[str | None, Query(min_length=1, max_length=36)] = None,
    prompt_id: Annotated[str | None, Query(min_length=1, max_length=36)] = None,
    feedback_level: Annotated[str | None, Query(min_length=1, max_length=32)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[FeedbackRecordRead]:
    """Return feedback records with learner, attempt, prompt, and level filters."""
    records = list_feedback_records(
        session,
        learner_id=learner_id,
        attempt_id=attempt_id,
        prompt_id=prompt_id,
        feedback_level=feedback_level,
        limit=limit,
    )
    return [FeedbackRecordRead.model_validate(record) for record in records]


@router.get("/feedback/{feedback_record_id}", response_model=FeedbackRecordRead)
def get_feedback_route(feedback_record_id: str, session: SessionDep) -> FeedbackRecordRead:
    """Return one feedback record."""
    record = get_feedback_record(session, feedback_record_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Feedback not found.")
    return FeedbackRecordRead.model_validate(record)


@router.post(
    "/feedback-actions",
    response_model=FeedbackActionRead,
    status_code=status.HTTP_201_CREATED,
)
def create_feedback_action_route(
    payload: FeedbackActionCreate, session: SessionDep
) -> FeedbackActionRead:
    """Create a feedback next action."""
    data = payload.model_dump()
    parent_record = None
    if data.get("feedback_record_id") is not None:
        parent_record = get_feedback_record(session, data["feedback_record_id"])
        if parent_record is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Referenced feedback record not found.",
            )
    action = create_feedback_action(session, **data)
    if parent_record is not None:
        parent_record.next_action_ids = [*(parent_record.next_action_ids or []), action.id]
        session.flush()
    session.commit()
    session.refresh(action)
    return FeedbackActionRead.model_validate(action)


@router.get("/feedback-actions", response_model=list[FeedbackActionRead])
def list_feedback_actions_route(
    session: SessionDep,
    learner_id: Annotated[str | None, Query(min_length=1, max_length=36)] = None,
    attempt_id: Annotated[str | None, Query(min_length=1, max_length=36)] = None,
    prompt_id: Annotated[str | None, Query(min_length=1, max_length=36)] = None,
    feedback_record_id: Annotated[str | None, Query(min_length=1, max_length=36)] = None,
    action_type: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
    status: Annotated[str | None, Query(min_length=1, max_length=32)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[FeedbackActionRead]:
    """Return feedback actions with learner-loop filters."""
    actions = list_feedback_actions(
        session,
        learner_id=learner_id,
        attempt_id=attempt_id,
        prompt_id=prompt_id,
        feedback_record_id=feedback_record_id,
        action_type=action_type,
        status=status,
        limit=limit,
    )
    return [FeedbackActionRead.model_validate(action) for action in actions]


@router.get("/feedback-actions/{feedback_action_id}", response_model=FeedbackActionRead)
def get_feedback_action_route(feedback_action_id: str, session: SessionDep) -> FeedbackActionRead:
    """Return one feedback action."""
    action = get_feedback_action(session, feedback_action_id)
    if action is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Feedback action not found."
        )
    return FeedbackActionRead.model_validate(action)
