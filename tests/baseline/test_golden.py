"""Golden masters of each scenario's flattened scheduling decision.

Re-bless after an intended change:
    pytest tests/baseline/test_golden.py --force-regen
then review and commit the updated baseline CSVs under test_golden/.
"""

from __future__ import annotations

from typing import Any

import pytest
from baseline_kit import check_metrics, load_catalog
from pytest_regressions.num_regression import NumericRegressionFixture

from . import adapter
from .conftest import CATALOG_PATH

_CATALOG = load_catalog(CATALOG_PATH)
_SCENARIOS = _CATALOG["scenarios"]


@pytest.mark.parametrize("scenario", _SCENARIOS, ids=[s["id"] for s in _SCENARIOS])
def test_scheduler_decision_golden(
    scenario: dict[str, Any], num_regression: NumericRegressionFixture
) -> None:
    check_metrics(num_regression, adapter.run_scenario(scenario))
