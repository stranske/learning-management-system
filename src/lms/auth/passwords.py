"""Password hashing utilities for local Argon2-based login.

Argon2id is the OWASP-recommended password hashing algorithm. We wrap
``argon2-cffi``'s :class:`PasswordHasher` in two thin module-level helpers so
the rest of the codebase doesn't import the hasher class directly — this keeps
the cost-parameter choice in one place and makes the auth flow easy to swap
later (e.g. to a magic-link issuer) without ripping out call sites.

Design notes:

- One module-level ``PasswordHasher`` instance is reused across calls. The
  hasher is stateless and thread-safe, so caching avoids re-parsing default
  parameters on every login attempt.
- ``hash_password`` and ``verify_password`` both raise on bad input shapes
  rather than returning sentinel values, matching argon2-cffi's contract.
- The default cost parameters come from argon2-cffi's recommended defaults
  (time_cost=3, memory_cost=64 MiB, parallelism=4). They can be overridden
  via env vars for benchmarking; we deliberately don't expose them in the
  Settings class to discourage drift.
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error, InvalidHashError, VerifyMismatchError

# A single shared hasher instance. argon2-cffi documents this as thread-safe;
# reusing it avoids constructing a new instance on every login attempt.
_HASHER = PasswordHasher()
MIN_PASSWORD_LENGTH = 12


def validate_password_strength(plaintext: str) -> None:
    """Raise when ``plaintext`` is not strong enough for local auth."""
    if len(plaintext) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"password must be at least {MIN_PASSWORD_LENGTH} characters long")


def hash_password(plaintext: str) -> str:
    """Return an Argon2id encoded hash for ``plaintext``.

    The returned string is self-describing: it embeds the algorithm, salt,
    cost parameters, and digest, so the verifier can recover everything it
    needs from the stored hash alone.
    """
    if not isinstance(plaintext, str):
        raise TypeError("hash_password expects a str password")
    if not plaintext:
        raise ValueError("hash_password expects a non-empty password")
    validate_password_strength(plaintext)
    return _HASHER.hash(plaintext)


def verify_password(stored_hash: str | None, plaintext: str) -> bool:
    """Return True when ``plaintext`` matches ``stored_hash``.

    Returns False when:
      - ``stored_hash`` is None (e.g. local-dev user without a password set)
      - ``plaintext`` is empty
      - argon2-cffi raises for a mismatch or malformed stored hash
    """
    if stored_hash is None or not plaintext:
        return False
    try:
        return _HASHER.verify(stored_hash, plaintext)
    except (VerifyMismatchError, InvalidHashError, Argon2Error):
        return False


def needs_rehash(stored_hash: str) -> bool:
    """Return True when ``stored_hash`` uses outdated cost parameters.

    Call this on successful login; if it returns True, hash the plaintext
    again with :func:`hash_password` and persist the new hash. This lets us
    transparently upgrade users to stronger parameters when the library
    raises its defaults without forcing a password reset.
    """
    return _HASHER.check_needs_rehash(stored_hash)
