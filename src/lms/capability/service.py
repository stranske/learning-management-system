"""Service facade for capability planning workflows."""

from __future__ import annotations

from lms.capability.repository import (
    create_gap_analysis,
    get_gap_analysis,
    list_gap_analyses,
    serialize_gap_analysis,
)

__all__ = [
    "create_gap_analysis",
    "get_gap_analysis",
    "list_gap_analyses",
    "serialize_gap_analysis",
]
