"""Authentication dependencies for development and test mode."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from lms.auth.models import User
from lms.auth.repository import get_or_create_local_dev_user
from lms.db.session import get_session

SessionDep = Annotated[Session, Depends(get_session)]


def get_current_user(session: SessionDep) -> User:
    """Return a local user placeholder until production auth is introduced."""
    return get_or_create_local_dev_user(session)
