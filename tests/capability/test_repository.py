"""Repository utility regression tests."""

from __future__ import annotations

from lms.capability.repository import _as_int


def test_as_int_handles_float_strings() -> None:
    assert _as_int("3.0") == 3
    assert _as_int("3.5") == 3
    assert _as_int("x") == 0
    assert _as_int(True) == 0


def test_as_int_handles_non_finite_strings() -> None:
    # int(float("inf")) raises OverflowError and int(float("nan")) raises ValueError;
    # the helper must return 0 for these rather than propagating.
    assert _as_int("inf") == 0
    assert _as_int("-inf") == 0
    assert _as_int("Infinity") == 0
    assert _as_int("nan") == 0
    assert _as_int(float("inf")) == 0
    assert _as_int(float("nan")) == 0
