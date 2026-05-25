"""Tests for local user identity."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from lms.auth import repository
from lms.auth.dependencies import get_current_user
from lms.auth.models import User
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


def test_create_local_user_allows_email_without_username(db_session: Session) -> None:
    """User creation supports email-only identity for future SSO migration paths."""
    user = create_local_user(
        db_session,
        username=None,
        display_name="Email Only",
        email="email-only@example.test",
    )
    db_session.commit()

    assert user.id
    assert user.username is None
    assert user.email == "email-only@example.test"
    assert user.is_local is True


def test_create_local_user_requires_email_or_username(db_session: Session) -> None:
    """User creation rejects records without either login identifier."""
    with pytest.raises(ValueError, match="Either username or email is required."):
        create_local_user(
            db_session,
            username=None,
            display_name="Invalid User",
            email=None,
        )


def test_local_dev_user_race_requeries_existing_user(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Concurrent local-dev creation recovers by re-querying after rollback."""
    existing = create_local_user(
        db_session,
        username="local-dev",
        display_name="Local Development User",
        email="local-dev@example.invalid",
    )
    db_session.commit()

    def raise_integrity_error(*args: object, **kwargs: object) -> User:
        raise IntegrityError("insert users", {}, Exception("duplicate username"))

    monkeypatch.setattr(repository, "create_local_user", raise_integrity_error)
    calls = {"count": 0}

    def stale_then_existing(session: Session, username: str) -> User | None:
        calls["count"] += 1
        if calls["count"] == 1:
            return None
        return session.query(User).filter(User.username == username).one_or_none()

    monkeypatch.setattr(repository, "get_user_by_username", stale_then_existing)

    user = get_or_create_local_dev_user(db_session)

    assert user.id == existing.id
