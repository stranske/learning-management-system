"""Repository utility regression tests."""

from __future__ import annotations

from lms.capability.repository import _as_int


def test_as_int_handles_float_strings() -> None:
    assert _as_int("3.0") == 3
    assert _as_int("3.5") == 3
    assert _as_int("x") == 0
    assert _as_int(True) == 0
