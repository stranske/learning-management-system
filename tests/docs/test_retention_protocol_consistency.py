"""Guard the project plan against restating the locked retention protocol."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROJECT_PLAN = ROOT / "docs" / "product" / "project-plan.md"


def test_plan_does_not_restate_protocol_differently() -> None:
    project_plan = PROJECT_PLAN.read_text()
    demo_section = _section_between(
        project_plan,
        "## Minimum Demo Criterion",
        "## Implementation Roadmap",
    )

    assert "](../handoff/demo-retention-protocol.md)" in demo_section
    assert "verbatim" not in demo_section
    assert "paraphrase" not in demo_section
    for category in ("complete", "partial", "gist-only", "missed"):
        assert f"`{category}`" in demo_section


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
