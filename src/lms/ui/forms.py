"""Shared helpers for parsing untrusted HTML form numeric fields."""

from __future__ import annotations

import math


class FormValueError(ValueError):
    """Raised when a posted form field cannot be parsed as the expected numeric type."""


def optional_int(value: str | None) -> int | None:
    """Parse optional integer form text, returning None for blank values."""
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        raise FormValueError("Enter a valid whole number for numeric form fields.") from None


def optional_float(value: str | None) -> float | None:
    """Parse optional float form text, returning None for blank values."""
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        parsed = float(text)
    except ValueError:
        raise FormValueError("Enter a valid number for numeric form fields.") from None
    if not math.isfinite(parsed):
        raise FormValueError("Enter a finite number for numeric form fields.") from None
    return parsed
