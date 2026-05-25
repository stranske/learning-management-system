"""Tests for learner profile persistence."""

from __future__ import annotations

from sqlalchemy.orm import Session

from lms.auth.repository import create_local_user
from lms.learners.repository import create_learner_for_user, list_learners_for_user


def test_create_learner_for_user(db_session: Session) -> None:
    """A learner profile is explicitly linked to a user id."""
    user = create_local_user(db_session, username="grace", display_name="Grace Hopper")
    learner = create_learner_for_user(
        db_session,
        user_id=user.id,
        display_name="Grace",
        timezone="America/Chicago",
    )
    db_session.commit()

    assert learner.id
    assert learner.user_id == user.id
    assert learner.display_name == "Grace"
    assert learner.timezone == "America/Chicago"
    assert learner.locale == "en-US"
    assert list_learners_for_user(db_session, user_id=user.id) == [learner]
