"""Repository helpers for local user identity."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from lms.auth.models import User

LOCAL_DEV_USERNAME = "local-dev"


def create_local_user(
    session: Session,
    *,
    username: str | None,
    display_name: str,
    email: str | None = None,
) -> User:
    """Create a local-development user."""
    if not username and not email:
        msg = "Either username or email is required."
        raise ValueError(msg)
    user = User(username=username, display_name=display_name, email=email, is_local=True)
    session.add(user)
    session.flush()
    return user


def get_user(session: Session, user_id: str) -> User | None:
    """Return a user by stable id."""
    return session.get(User, user_id)


def get_user_by_username(session: Session, username: str) -> User | None:
    """Return a user by username."""
    return session.scalar(select(User).where(User.username == username))


def get_or_create_local_dev_user(session: Session) -> User:
    """Return the deterministic local-development user, creating it if needed."""
    existing = get_user_by_username(session, LOCAL_DEV_USERNAME)
    if existing is not None:
        return existing
    try:
        return create_local_user(
            session,
            username=LOCAL_DEV_USERNAME,
            display_name="Local Development User",
            email="local-dev@example.invalid",
        )
    except IntegrityError:
        session.rollback()
        existing = get_user_by_username(session, LOCAL_DEV_USERNAME)
        if existing is None:
            raise
        return existing
