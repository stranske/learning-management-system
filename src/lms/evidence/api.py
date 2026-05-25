"""HTTP routes for learner attempts."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from lms.db.session import get_session
from lms.evidence.repository import create_attempt, get_attempt, list_evidence_records
from lms.evidence.schemas import AttemptCreate, AttemptRead, EvidenceRecordRead

router = APIRouter(prefix="/attempts", tags=["attempts"])
evidence_router = APIRouter(prefix="/evidence-records", tags=["evidence-records"])
SessionDep = Annotated[Session, Depends(get_session)]


@router.post("", response_model=AttemptRead, status_code=status.HTTP_201_CREATED)
def create_attempt_route(payload: AttemptCreate, session: SessionDep) -> AttemptRead:
    """Record a learner attempt."""
    attempt = create_attempt(
        session,
        **payload.model_dump(),
    )
    session.commit()
    session.refresh(attempt)
    return AttemptRead.model_validate(attempt)


@router.get("/{attempt_id}", response_model=AttemptRead)
def get_attempt_route(attempt_id: str, session: SessionDep) -> AttemptRead:
    """Return a learner attempt."""
    attempt = get_attempt(session, attempt_id)
    if attempt is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attempt not found.")
    return AttemptRead.model_validate(attempt)


@evidence_router.get("", response_model=list[EvidenceRecordRead])
def list_evidence_records_route(
    session: SessionDep,
    learner_id: Annotated[str | None, Query(min_length=1, max_length=36)] = None,
    knowledge_node_id: Annotated[str | None, Query(min_length=1, max_length=36)] = None,
    evidence_kind: Annotated[str | None, Query(pattern="^(observed|inferred)$")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[EvidenceRecordRead]:
    """Return evidence records filtered by learner, node, or evidence kind."""
    return [
        EvidenceRecordRead.model_validate(record)
        for record in list_evidence_records(
            session,
            learner_id=learner_id,
            knowledge_node_id=knowledge_node_id,
            evidence_kind=evidence_kind,
            limit=limit,
        )
    ]
