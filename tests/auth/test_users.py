"""Tests for local user identity."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from lms.auth import repository
from lms.auth.dependencies import get_current_user
from lms.auth.models import User
from lms.auth.repository import authenticate, create_local_user, get_or_create_local_dev_user
from lms.auth.schemas import UserCreate


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


def test_user_create_rejects_malformed_email() -> None:
    with pytest.raises(ValueError):
        UserCreate(username="ada", display_name="Ada Lovelace", email="not-an-email")


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


def test_authenticate_missing_user_uses_timing_equalizer(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unknown usernames still run a password verify to equalize latency."""
    sentinel_hash = "equalizer-hash"
    seen: list[tuple[str | None, str]] = []

    monkeypatch.setattr(repository, "_timing_equalizer_hash", lambda: sentinel_hash)

    def fake_verify(stored_hash: str | None, plaintext: str) -> bool:
        seen.append((stored_hash, plaintext))
        return False

    monkeypatch.setattr(repository, "verify_password", fake_verify)

    user = authenticate(db_session, username="missing-user", password="pw-1234567890ab")

    assert user is None
    assert seen == [(sentinel_hash, "pw-1234567890ab")]


def test_authenticate_existing_user_checks_user_hash(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Known usernames verify against the user's stored hash, not equalizer hash."""
    user = create_local_user(
        db_session,
        username="ada-auth",
        display_name="Ada Auth",
        password="long-password-1234",
    )
    db_session.flush()

    seen: list[tuple[str | None, str]] = []

    def fake_verify(stored_hash: str | None, plaintext: str) -> bool:
        seen.append((stored_hash, plaintext))
        return False

    monkeypatch.setattr(repository, "verify_password", fake_verify)

    authed = authenticate(db_session, username="ada-auth", password="wrong-password-1234")

    assert authed is None
    assert len(seen) == 1
    assert seen[0] == (user.password_hash, "wrong-password-1234")
