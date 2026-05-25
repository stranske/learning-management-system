"""HTTP routes for learner attempts."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from lms.db.session import get_session
from lms.evidence.repository import create_attempt, get_attempt
from lms.evidence.schemas import AttemptCreate, AttemptRead

router = APIRouter(prefix="/attempts", tags=["attempts"])
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
