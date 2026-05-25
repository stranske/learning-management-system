"""Tests for local user identity."""

from __future__ import annotations

from sqlalchemy.orm import Session

from lms.auth.dependencies import get_current_user
from lms.auth.repository import create_local_user, get_or_create_local_dev_user


def test_create_local_user(db_session: Session) -> None:
    """A local user has a stable id, display name, and local-auth marker."""
    user = create_local_user(
        db_session,
        username="ada",
        display_name="Ada Lovelace",
        email="ada@example.test",
    )
    db_session.commit()

    assert user.id
    assert user.username == "ada"
    assert user.display_name == "Ada Lovelace"
    assert user.email == "ada@example.test"
    assert user.is_local is True
    assert user.created_at is not None
    assert user.updated_at is not None


def test_development_auth_dependency_returns_local_user(db_session: Session) -> None:
    """The placeholder auth dependency creates and reuses a deterministic user."""
    user = get_current_user(db_session)
    reused = get_or_create_local_dev_user(db_session)

    assert user.id == reused.id
    assert user.username == "local-dev"
    assert user.is_local is True
