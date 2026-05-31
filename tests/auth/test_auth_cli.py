"""Tests for the ``lms auth ...`` bootstrap CLI.

These cover ``_dispatch_auth`` / ``_resolve_password`` (``src/lms/__main__.py``),
the documented mechanism for bootstrapping users on a deployed
``AUTH_REQUIRED=true`` instance (see ``docs/architecture/auth.md``). The happy
paths and every error branch (duplicate username, missing user, password
confirmation mismatch, empty/omitted password) were previously untested.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from sqlalchemy.orm import Session

import lms.__main__ as lms_main
import lms.auth.models  # noqa: F401  # register Base.metadata for db_session
from lms.auth.repository import create_local_user, get_user_by_username


@pytest.fixture
def patched_session(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> Session:
    """Route ``lms auth`` ``session_scope()`` onto the in-memory test session."""

    @contextmanager
    def fake_session_scope() -> Iterator[Session]:
        yield db_session

    monkeypatch.setattr(lms_main, "session_scope", fake_session_scope)
    return db_session


def _run(monkeypatch: pytest.MonkeyPatch, *argv: str) -> None:
    monkeypatch.setattr("sys.argv", ["lms", *argv])
    lms_main.main()


def test_create_user_happy_path_prints_id(
    patched_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """create-user persists the user and prints its id + username."""
    _run(
        monkeypatch,
        "auth",
        "create-user",
        "--username",
        "ada",
        "--display-name",
        "Ada Lovelace",
        "--password",
        "correct horse",
    )

    out = capsys.readouterr().out.strip()
    assert out.startswith("created user: id=")
    assert "username=ada" in out

    user = get_user_by_username(patched_session, "ada")
    assert user is not None
    assert user.display_name == "Ada Lovelace"
    # Plaintext is never stored; the password was hashed.
    assert user.password_hash is not None
    assert "correct horse" not in user.password_hash


def test_create_user_duplicate_exits_nonzero(
    patched_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """create-user for an existing username exits non-zero (named AC)."""
    create_local_user(
        patched_session,
        username="ada",
        display_name="Ada Lovelace",
        password="first-pass",
    )
    patched_session.flush()

    with pytest.raises(SystemExit) as excinfo:
        _run(
            monkeypatch,
            "auth",
            "create-user",
            "--username",
            "ada",
            "--display-name",
            "Ada Again",
            "--password",
            "second-pass",
        )
    # A string SystemExit code is non-zero (printed to stderr, exit status 1).
    assert excinfo.value.code == "user already exists: ada"


def test_set_password_for_missing_user_errors(
    patched_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """set-password for a username that does not exist exits with an error."""
    with pytest.raises(SystemExit) as excinfo:
        _run(
            monkeypatch,
            "auth",
            "set-password",
            "--username",
            "ghost",
            "--password",
            "whatever",
        )
    assert excinfo.value.code == "user not found: ghost"


def test_set_password_updates_existing_user(
    patched_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """set-password rotates an existing user's hash and confirms the rotation."""
    user = create_local_user(
        patched_session,
        username="ada",
        display_name="Ada Lovelace",
        password="old-pass",
    )
    patched_session.flush()
    original_hash = user.password_hash

    _run(
        monkeypatch,
        "auth",
        "set-password",
        "--username",
        "ada",
        "--password",
        "brand-new-pass",
    )

    out = capsys.readouterr().out.strip()
    assert out == "password updated: username=ada"
    refreshed = get_user_by_username(patched_session, "ada")
    assert refreshed is not None
    assert refreshed.password_hash is not None
    assert refreshed.password_hash != original_hash


def test_password_confirmation_mismatch_exits(
    patched_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Interactive ``--password`` (prompt) with mismatched entries exits."""
    answers = iter(["typed-one", "typed-two"])
    monkeypatch.setattr("getpass.getpass", lambda prompt="": next(answers))

    with pytest.raises(SystemExit) as excinfo:
        _run(
            monkeypatch,
            "auth",
            "create-user",
            "--username",
            "ada",
            "--display-name",
            "Ada Lovelace",
            "--password",  # nargs="?" -> const "__PROMPT__"
        )
    assert excinfo.value.code == "passwords did not match"


def test_password_prompt_empty_exits(
    patched_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Interactive prompt that matches but is empty is rejected."""
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "")

    with pytest.raises(SystemExit) as excinfo:
        _run(
            monkeypatch,
            "auth",
            "create-user",
            "--username",
            "ada",
            "--display-name",
            "Ada Lovelace",
            "--password",
        )
    assert excinfo.value.code == "password cannot be empty"


def test_password_omitted_is_required(
    patched_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """create-user without any ``--password`` exits asking for one."""
    with pytest.raises(SystemExit) as excinfo:
        _run(
            monkeypatch,
            "auth",
            "create-user",
            "--username",
            "ada",
            "--display-name",
            "Ada Lovelace",
        )
    assert "password is required" in str(excinfo.value.code)
