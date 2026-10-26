"""Keep execution runtimes current without changing the supported Python floor."""

from __future__ import annotations

import json
import re
from collections.abc import Hashable, Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"
RUNTIME_KEYS = {
    "python-version",
    "python-versions",
    "primary-python-version",
    "coverage-python-version",
    "PYTHON_VERSION",
    "COVERAGE_REFERENCE_RUNTIME",
}
OLD_RUNTIME = re.compile(r"(?<![\w.])3\.12(?:\.\d+)?(?![\w.])")


class WorkflowLoader(yaml.BaseLoader):
    """Preserve version spelling and reject mappings that hide duplicate pins."""

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[Hashable, Any]:
        mapping: dict[Hashable, Any] = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in mapping:
                raise ValueError(f"duplicate workflow key: {key}")
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


def runtime_pins(value: object) -> Iterator[tuple[str, object]]:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in RUNTIME_KEYS:
                yield key, child
            yield from runtime_pins(child)
    elif isinstance(value, list):
        for child in value:
            yield from runtime_pins(child)


def old_runtime_pins(text: str) -> list[tuple[str, object]]:
    workflow = yaml.load(text, Loader=WorkflowLoader)
    return [(key, value) for key, value in runtime_pins(workflow) if OLD_RUNTIME.search(str(value))]


def test_workflow_python_pins_follow_standard() -> None:
    paths = sorted({*WORKFLOWS.glob("*.yml"), *WORKFLOWS.glob("*.yaml")})
    assert paths, "no workflows were inspected"
    offenders = [(path.name, old_runtime_pins(path.read_text())) for path in paths]
    assert not [(path, pins) for path, pins in offenders if pins]

    for filename, job in [("ci.yml", "python"), ("pr-00-gate.yml", "python-ci")]:
        workflow = yaml.load((WORKFLOWS / filename).read_text(), Loader=WorkflowLoader)
        inputs = workflow["jobs"][job]["with"]
        assert json.loads(inputs["python-versions"]) == ["3.13", "3.14"]
        assert inputs["primary-python-version"] == "3.14"
        assert inputs["coverage-python-version"] == "3.14"

    gate = yaml.load((WORKFLOWS / "pr-00-gate.yml").read_text(), Loader=WorkflowLoader)
    for job in ("compose-smoke", "fork-status-replay"):
        setup_steps = [
            step
            for step in gate["jobs"][job]["steps"]
            if step.get("uses", "").startswith("actions/setup-python@")
        ]
        assert setup_steps, f"{job}: missing setup-python step"
        for step in setup_steps:
            assert step["with"]["python-version"] == "3.14", job


@pytest.mark.parametrize("key", sorted(RUNTIME_KEYS))
@pytest.mark.parametrize(
    "value", ['"3.12"', "3.12", "3.12.9", '\'["3.12", "3.14"]\'', "[3.12, '3.14']"]
)
def test_guard_detects_quoted_numeric_and_matrix_pins(key: str, value: str) -> None:
    assert old_runtime_pins(f"jobs:\n  test:\n    with:\n      {key}: {value}\n")


def test_guard_preserves_distinct_versions_and_lock_generation_floor() -> None:
    assert not old_runtime_pins(
        "jobs:\n  lock:\n    with:\n      python-version: 3.120\n"
        "    steps:\n      - run: uv pip compile --universal --python-version 3.12\n"
    )


def test_duplicate_runtime_mapping_cannot_hide_a_pin() -> None:
    with pytest.raises(ValueError, match="duplicate workflow key: with"):
        old_runtime_pins(
            "jobs:\n  test:\n    with:\n      python-version: '3.12'\n"
            "    with:\n      python-version: '3.14'\n"
        )


@pytest.mark.parametrize("job", ["compose-smoke", "fork-status-replay"])
@pytest.mark.parametrize("version", ["3.12", "3.13"])
def test_named_guard_rejects_standalone_runtime_regression(
    workflow_copy: Path, job: str, version: str
) -> None:
    gate_path = workflow_copy / "pr-00-gate.yml"
    gate = yaml.load(gate_path.read_text(), Loader=WorkflowLoader)
    setup_step = next(
        step
        for step in gate["jobs"][job]["steps"]
        if step.get("uses", "").startswith("actions/setup-python@")
    )
    setup_step["with"]["python-version"] = version
    gate_path.write_text(yaml.safe_dump(gate))

    with pytest.raises(AssertionError):
        test_workflow_python_pins_follow_standard()


@pytest.fixture
def workflow_copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    # Mutate temporary copies so the repository workflows remain untouched.
    for path in {*WORKFLOWS.glob("*.yml"), *WORKFLOWS.glob("*.yaml")}:
        (tmp_path / path.name).write_bytes(path.read_bytes())
    monkeypatch.setattr(__name__ + ".WORKFLOWS", tmp_path)
    return tmp_path


@pytest.mark.parametrize("filename, job", [("ci.yml", "python"), ("pr-00-gate.yml", "python-ci")])
def test_named_guard_rejects_retired_matrix_and_accepts_restoration(
    workflow_copy: Path, filename: str, job: str
) -> None:
    path = workflow_copy / filename
    original = path.read_bytes()
    workflow = yaml.load(original, Loader=WorkflowLoader)
    workflow["jobs"][job]["with"]["python-versions"] = '["3.12", "3.14"]'
    path.write_text(yaml.safe_dump(workflow))

    try:
        with pytest.raises(AssertionError):
            test_workflow_python_pins_follow_standard()
    finally:
        path.write_bytes(original)

    test_workflow_python_pins_follow_standard()
