"""Local-development auth API routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from lms.auth.models import User
from lms.auth.repository import create_local_user
from lms.auth.schemas import UserCreate, UserRead
from lms.db.session import get_session

router = APIRouter(prefix="/auth", tags=["auth"])
SessionDep = Annotated[Session, Depends(get_session)]


@router.post("/users", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user(payload: UserCreate, session: SessionDep) -> User:
    """Create a local-development user identity."""
    try:
        user = create_local_user(
            session,
            username=payload.username,
            display_name=payload.display_name,
            email=payload.email,
        )
        session.commit()
        session.refresh(user)
        return user
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with that username or email already exists.",
        ) from exc
