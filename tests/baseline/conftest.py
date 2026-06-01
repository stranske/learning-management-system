"""Fixtures and catalog loading for the LMS baseline kit."""

from __future__ import annotations

import functools
import sys
from pathlib import Path
from typing import Any

import pytest

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
SRC_ROOT = REPO_ROOT / "src"
CATALOG_PATH = HERE / "catalog.yaml"

# Ensure the package is importable under pytest (mirrors pyproject pythonpath).
for candidate in (SRC_ROOT, REPO_ROOT):
    if candidate.exists() and str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))


@functools.lru_cache(maxsize=1)
def load_catalog_cached() -> dict[str, Any]:
    from baseline_kit import load_catalog

    catalog: dict[str, Any] = load_catalog(CATALOG_PATH)
    return catalog


def scenarios_by_id() -> dict[str, dict[str, Any]]:
    return {s["id"]: s for s in load_catalog_cached()["scenarios"]}


@pytest.fixture(scope="session")
def catalog() -> dict[str, Any]:
    return load_catalog_cached()
