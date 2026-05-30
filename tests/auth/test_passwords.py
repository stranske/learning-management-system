"""Tests for the Argon2 password helpers (#180)."""

from __future__ import annotations

import pytest

from lms.auth.passwords import hash_password, needs_rehash, verify_password


def test_hash_password_returns_an_encoded_argon2_hash() -> None:
    """Hash strings are Argon2id encoded, embedding algorithm + params + salt + digest."""
    h = hash_password("correct horse battery staple")
    # Argon2id encoded hashes look like ``$argon2id$v=19$m=..,t=..,p=..$<salt>$<hash>``
    assert h.startswith("$argon2id$")
    # The plaintext must not appear in the encoded form.
    assert "correct horse" not in h


def test_hash_password_rejects_empty_string() -> None:
    with pytest.raises(ValueError):
        hash_password("")


def test_hash_password_rejects_non_string() -> None:
    with pytest.raises(TypeError):
        hash_password(12345)  # type: ignore[arg-type]


def test_verify_password_accepts_correct_password() -> None:
    h = hash_password("sw0rdfish")
    assert verify_password(h, "sw0rdfish") is True


def test_verify_password_rejects_wrong_password() -> None:
    h = hash_password("sw0rdfish")
    assert verify_password(h, "letmein") is False


def test_verify_password_handles_none_hash() -> None:
    """The local-dev shortcut user has no password — verify must return False, not crash."""
    assert verify_password(None, "anything") is False


def test_verify_password_handles_empty_plaintext() -> None:
    h = hash_password("real-password")
    assert verify_password(h, "") is False


def test_two_hashes_of_same_password_differ_in_salt() -> None:
    """Argon2 uses a random salt per hash; the encoded form must therefore differ."""
    h1 = hash_password("same-password")
    h2 = hash_password("same-password")
    assert h1 != h2
    # But both must still verify against the original plaintext.
    assert verify_password(h1, "same-password") is True
    assert verify_password(h2, "same-password") is True


def test_needs_rehash_returns_false_for_freshly_hashed_password() -> None:
    """A hash freshly created with default params doesn't need rehashing."""
    h = hash_password("freshly-hashed")
    assert needs_rehash(h) is False
