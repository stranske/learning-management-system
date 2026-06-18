"""Guard the Minimum Demo docs against capability-surface scope drift."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

MINIMUM_DEMO_HANDOFF_DOCS = (
    ROOT / "docs" / "handoff" / "minimum-demo-coverage.md",
    ROOT / "docs" / "handoff" / "demo-retention-protocol.md",
)

FORBIDDEN_DEMO_REQUIREMENTS = (
    "/capability",
    "/app/learner/capability",
    "CapabilityTarget",
    "CapabilityEstimate",
    "GapAnalysis",
    "MaintenancePlan",
)


def test_minimum_demo_project_plan_excludes_capability_requirements() -> None:
    project_plan = (ROOT / "docs" / "product" / "project-plan.md").read_text()
    required_steps = _section_between(
        project_plan,
        "1. Import ~10 research notes",
        "Implemented preview surfaces outside this list",
    )

    for forbidden in FORBIDDEN_DEMO_REQUIREMENTS:
        assert forbidden not in required_steps, (
            f"{forbidden} leaked into project-plan.md Minimum Demo criterion"
        )


def test_minimum_demo_handoff_steps_exclude_capability_requirements() -> None:
    for doc_path in MINIMUM_DEMO_HANDOFF_DOCS:
        demo_steps = _demo_steps(doc_path.read_text())
        for forbidden in FORBIDDEN_DEMO_REQUIREMENTS:
            assert forbidden not in demo_steps, f"{forbidden} leaked into {doc_path}"


def _section_between(text: str, start_marker: str, end_marker: str) -> str:
    try:
        start = text.index(start_marker)
    except ValueError as exc:
        raise ValueError(f"start marker not found: {start_marker}") from exc
    try:
        end = text.index(end_marker, start)
    except ValueError as exc:
        raise ValueError(f"end marker not found: {end_marker}") from exc
    return text[start:end]


def _demo_steps(text: str) -> str:
    if "## Real Demo Manual Steps" not in text:
        return text
    return text.split("## Real Demo Manual Steps", maxsplit=1)[1]
