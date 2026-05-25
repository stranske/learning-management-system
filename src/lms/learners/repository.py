"""Repository helpers for learner profiles."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from lms.learners.models import Learner


def create_learner_for_user(
    session: Session,
    *,
    user_id: str,
    display_name: str,
    timezone: str = "UTC",
    locale: str = "en-US",
) -> Learner:
    """Create a learner profile for an explicit user id."""
    learner = Learner(
        user_id=user_id,
        display_name=display_name,
        timezone=timezone,
        locale=locale,
    )
    session.add(learner)
    session.flush()
    return learner


def get_learner(session: Session, *, learner_id: str) -> Learner | None:
    """Return a learner by explicit learner id."""
    return session.get(Learner, learner_id)


def list_learners_for_user(session: Session, *, user_id: str) -> list[Learner]:
    """Return learner profiles for an explicit user id."""
    return list(session.scalars(select(Learner).where(Learner.user_id == user_id)))
