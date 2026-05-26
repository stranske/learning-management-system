"""Tests for the M4 Minimum Demo smoke path."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import lms.__main__ as lms_main
from lms.demo import build_minimum_demo_smoke_summary, render_minimum_demo_smoke


def test_minimum_demo_smoke_path(monkeypatch: Any, capsys: Any) -> None:
    """The smoke path covers the six Minimum Demo requirements in fake-provider mode."""
    summary = build_minimum_demo_smoke_summary()

    assert len(summary.notes) == 10
    assert len(summary.prompts) == 30
    assert len(summary.attempts) == 30
    assert len(summary.evidence) == 30
    assert summary.review_reason_codes == (
        "due-review",
        "mixed-practice",
        "new-instruction",
        "remediation",
    )
    assert len(summary.inspect_rows) == 10
    assert len(summary.llm_sessions) == 10
    assert {session.mode for session in summary.llm_sessions} == {"study-coach"}
    assert {session.trace_class for session in summary.llm_sessions} == {"formative"}

    rendered = render_minimum_demo_smoke(summary)
    assert "notes=10" in rendered
    assert "prompts=30" in rendered
    assert "evidence_rows=30" in rendered
    assert "study_coach_sessions=10" in rendered
    assert "daily_cost_micro_usd=" in rendered

    monkeypatch.setattr("sys.argv", ["lms", "demo", "smoke"])
    lms_main.main()

    output = capsys.readouterr().out
    assert "minimum demo smoke: ok" in output
    assert (
        "review_queue_reason_codes=due-review,mixed-practice,new-instruction,remediation" in output
    )


def test_minimum_demo_docs_are_locked_before_item_selection() -> None:
    """The protocol and coverage docs preserve the pre-registration contract."""
    protocol = Path("docs/handoff/demo-retention-protocol.md").read_text(encoding="utf-8")
    coverage = Path("docs/handoff/minimum-demo-coverage.md").read_text(encoding="utf-8")

    assert "locked before real item selection" in protocol
    assert "4 system-routed" in protocol
    assert "4 passive comparison" in protocol
    assert "day-30 unaided free recall" in protocol
    assert "10 notes" in coverage
    assert "30 prompts" in coverage
    assert "lms demo smoke" in coverage
