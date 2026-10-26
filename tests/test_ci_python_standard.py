"""Keep execution runtimes current without changing the supported Python floor."""

from __future__ import annotations

import json
import re
from pathlib import Path

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

    def construct_mapping(self, node, deep=False):
        mapping = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in mapping:
                raise ValueError(f"duplicate workflow key: {key}")
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


def runtime_pins(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if key in RUNTIME_KEYS:
                yield key, child
            yield from runtime_pins(child)
    elif isinstance(value, list):
        for child in value:
            yield from runtime_pins(child)


def old_runtime_pins(text):
    workflow = yaml.load(text, Loader=WorkflowLoader)
    return [(key, value) for key, value in runtime_pins(workflow) if OLD_RUNTIME.search(str(value))]


def test_workflow_python_pins_follow_standard():
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


@pytest.mark.parametrize(
    "value", ['"3.12"', "3.12", "3.12.9", '\'["3.12", "3.14"]\'', "[3.12, '3.14']"]
)
def test_guard_detects_quoted_numeric_and_matrix_pins(value):
    assert old_runtime_pins(f"jobs:\n  test:\n    with:\n      python-versions: {value}\n")


def test_guard_preserves_distinct_versions_and_lock_generation_floor():
    assert not old_runtime_pins(
        "jobs:\n  lock:\n    with:\n      python-version: 3.120\n"
        "    steps:\n      - run: uv pip compile --universal --python-version 3.12\n"
    )


def test_duplicate_runtime_mapping_cannot_hide_a_pin():
    with pytest.raises(ValueError, match="duplicate workflow key: with"):
        old_runtime_pins(
            "jobs:\n  test:\n    with:\n      python-version: '3.12'\n"
            "    with:\n      python-version: '3.14'\n"
        )
