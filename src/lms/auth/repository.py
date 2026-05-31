"""Repository helpers for local user identity."""

from __future__ import annotations

from functools import lru_cache

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from lms.auth.models import User
from lms.auth.passwords import hash_password, needs_rehash, verify_password

LOCAL_DEV_USERNAME = "local-dev"


@lru_cache(maxsize=1)
def _timing_equalizer_hash() -> str:
    """Return a throwaway Argon2 hash used to equalize ``authenticate`` timing.

    Verifying against this hash in the user-not-found branch makes that path
    cost roughly the same as a real password check, so an attacker cannot use
    response latency to tell which usernames exist. Computed once and cached.
    """
    return hash_password("timing-equalizer-not-a-real-credential")


def create_local_user(
    session: Session,
    *,
    username: str,
    display_name: str,
    email: str | None = None,
    password: str | None = None,
) -> User:
    """Create a local-development user.

    When ``password`` is provided it is hashed via Argon2 before being stored;
    the plaintext is never persisted. Pass ``None`` (the default) for the
    local-dev shortcut user that doesn't need credentials.
    """
    user = User(
        username=username,
        display_name=display_name,
        email=email,
        is_local=True,
        password_hash=hash_password(password) if password else None,
    )
    session.add(user)
    session.flush()
    return user


def authenticate(session: Session, *, username: str, password: str) -> User | None:
    """Return the user when ``username`` + ``password`` match, else None.

    On a successful login whose stored hash uses outdated cost parameters,
    transparently re-hash with the current defaults and persist the upgrade
    so users benefit from stronger settings without a password reset.
    """
    user = get_user_by_username(session, username)
    if user is None:
        # Defeat username enumeration: spend the same Argon2 verify cost as the
        # found-user path before returning, so response latency does not leak
        # whether the username exists. (verify_password short-circuits on an
        # empty password, which the real-user path does too, so timing stays
        # symmetric in that case as well.)
        verify_password(_timing_equalizer_hash(), password)
        return None
    if not verify_password(user.password_hash, password):
        return None
    # Transparent upgrade path: rehash with current cost params if needed.
    if user.password_hash is not None and needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
        session.flush()
    return user


def set_password(session: Session, user: User, *, password: str) -> None:
    """Hash ``password`` and store it on ``user``.

    Used by the bootstrap CLI to create the first credentialed user on a
    fresh deployment. Empty passwords are rejected by ``hash_password``.
    """
    user.password_hash = hash_password(password)
    session.flush()


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
        user = create_local_user(
            session,
            username=LOCAL_DEV_USERNAME,
            display_name="Local Development User",
            email="local-dev@example.invalid",
        )
        session.commit()
        return user
    except IntegrityError:
        session.rollback()
        existing = get_user_by_username(session, LOCAL_DEV_USERNAME)
        if existing is None:
            raise
        return existing
