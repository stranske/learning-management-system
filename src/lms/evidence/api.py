"""HTTP routes for learner attempts and evidence records."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from lms.auth.login import SettingsDep
from lms.db.session import get_session
from lms.evidence.repository import (
    get_attempt,
    get_evidence_record,
    list_evidence_records,
)
from lms.evidence.schemas import AttemptCreate, AttemptRead, EvidenceRecordRead
from lms.evidence.service import record_attempt
from lms.learners.identity import (
    CurrentUserDep,
    require_learner_ownership,
    resolve_learner_id,
)

router = APIRouter(tags=["evidence"])
SessionDep = Annotated[Session, Depends(get_session)]


@router.post("/attempts", response_model=AttemptRead, status_code=status.HTTP_201_CREATED)
def create_attempt_route(
    payload: AttemptCreate,
    session: SessionDep,
    current_user: CurrentUserDep,
    settings: SettingsDep,
) -> AttemptRead:
    """Record a learner attempt."""
    require_learner_ownership(
        session, user=current_user, settings=settings, learner_id=payload.learner_id
    )
    recorded = record_attempt(
        session,
        **payload.model_dump(),
    )
    session.commit()
    attempt = recorded.attempt
    session.refresh(attempt)
    return AttemptRead.model_validate(attempt)


@router.get("/attempts/{attempt_id}", response_model=AttemptRead)
def get_attempt_route(
    attempt_id: str,
    session: SessionDep,
    current_user: CurrentUserDep,
    settings: SettingsDep,
) -> AttemptRead:
    """Return a learner attempt."""
    attempt = get_attempt(session, attempt_id)
    if attempt is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attempt not found.")
    require_learner_ownership(
        session, user=current_user, settings=settings, learner_id=attempt.learner_id
    )
    return AttemptRead.model_validate(attempt)


@router.get("/evidence-records", response_model=list[EvidenceRecordRead])
def list_evidence_records_route(
    session: SessionDep,
    current_user: CurrentUserDep,
    settings: SettingsDep,
    learner_id: Annotated[
        str | None, Query(min_length=1, max_length=36, description="Filter by learner id.")
    ] = None,
    knowledge_node_id: Annotated[
        str | None,
        Query(min_length=1, max_length=36, description="Filter by knowledge node id."),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[EvidenceRecordRead]:
    """Return verbose evidence records with learner/node filters."""
    scoped_learner_id = (
        resolve_learner_id(session, user=current_user, settings=settings, requested=learner_id)
        if settings.auth_required
        else learner_id
    )
    records = list_evidence_records(
        session,
        learner_id=scoped_learner_id,
        knowledge_node_id=knowledge_node_id,
        limit=limit,
    )
    return [EvidenceRecordRead.model_validate(record) for record in records]


@router.get("/evidence-records/{evidence_record_id}", response_model=EvidenceRecordRead)
def get_evidence_record_route(
    evidence_record_id: str,
    session: SessionDep,
    current_user: CurrentUserDep,
    settings: SettingsDep,
) -> EvidenceRecordRead:
    """Return one verbose evidence record."""
    record = get_evidence_record(session, evidence_record_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Evidence record not found."
        )
    require_learner_ownership(
        session, user=current_user, settings=settings, learner_id=record.learner_id
    )
    return EvidenceRecordRead.model_validate(record)
