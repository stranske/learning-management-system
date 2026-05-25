"""Build-time research registry validation."""

from __future__ import annotations

from lms.research_registry.validator import (
    ResearchRegistry,
    ResearchRegistryError,
    load_registry,
    validate_registry,
)

__all__ = [
    "ResearchRegistry",
    "ResearchRegistryError",
    "load_registry",
    "validate_registry",
]
