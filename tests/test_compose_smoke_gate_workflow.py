"""Workflow contract for the Docker Compose startup smoke gate."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_pr_gate_runs_named_compose_smoke_check() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/pr-00-gate.yml").read_text())
    jobs = workflow["jobs"]

    compose_smoke = jobs["compose-smoke"]
    assert compose_smoke["name"] == "Compose smoke"

    step_names = [step["name"] for step in compose_smoke["steps"]]
    assert "Run Docker Compose startup smoke" in step_names

    smoke_step = next(
        (
            step
            for step in compose_smoke["steps"]
            if step["name"] == "Run Docker Compose startup smoke"
        ),
        None,
    )
    assert smoke_step is not None, "Run Docker Compose startup smoke step not found"
    assert smoke_step["env"]["LMS_RUN_COMPOSE_SMOKE"] == "1"
    assert smoke_step["run"] == "uv run pytest tests/test_compose_smoke.py -q --no-cov"

    summary_needs = set(jobs["summary"]["needs"])
    assert "compose-smoke" in summary_needs
