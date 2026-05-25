"""Learner API routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from lms.auth.dependencies import get_current_user
from lms.auth.models import User
from lms.auth.repository import get_user
from lms.db.session import get_session
from lms.learners.models import Learner
from lms.learners.repository import create_learner_for_user
from lms.learners.schemas import LearnerCreate, LearnerRead

router = APIRouter(prefix="/learners", tags=["learners"])
SessionDep = Annotated[Session, Depends(get_session)]
CurrentUserDep = Annotated[User, Depends(get_current_user)]


@router.post("", response_model=LearnerRead, status_code=status.HTTP_201_CREATED)
def create_learner(
    payload: LearnerCreate,
    session: SessionDep,
    _current_user: CurrentUserDep,
) -> Learner:
    """Create a learner profile for an explicit user id."""
    if get_user(session, payload.user_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    learner = create_learner_for_user(
        session,
        user_id=payload.user_id,
        display_name=payload.display_name,
        timezone=payload.timezone,
        locale=payload.locale,
    )
    session.commit()
    session.refresh(learner)
    return learner
