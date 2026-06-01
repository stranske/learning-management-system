"""Directional ("metamorphic") checks: variant vs control on a flat metric.

Each catalog `directionals` entry asserts an economically/pedagogically expected
movement, e.g. a failed retrieval shortens the interval and raises priority;
repeated success grows the interval; using a hint behaves like low confidence.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from baseline_kit import evaluate_direction, load_catalog

from . import adapter
from .conftest import CATALOG_PATH

_CATALOG = load_catalog(CATALOG_PATH)
_SCENARIOS = {s["id"]: s for s in _CATALOG["scenarios"]}
_DIRECTIONALS = _CATALOG["directionals"]


def _metric(scenario_id: str, key: str) -> float:
    return float(adapter.run_scenario(_SCENARIOS[scenario_id])[key])


@pytest.mark.parametrize("scen", _DIRECTIONALS, ids=[s["id"] for s in _DIRECTIONALS])
def test_directional(scen: dict[str, Any], record_property: Callable[[str, object], None]) -> None:
    metric = scen["metric"]
    variant = _metric(scen["scenario"], metric)
    control = _metric(scen["control"], metric)
    holds = evaluate_direction(scen["direction"], variant, control)
    msg = (
        f"{scen['id']}: {metric} variant={variant:.6g} "
        f"{scen['direction']} control={control:.6g} -> {holds}"
    )
    record_property("directional", msg)
    if scen.get("enforce"):
        assert holds, "Pedagogically wrong direction -- " + msg
    elif not holds:
        pytest.skip("[report-only] " + msg)
