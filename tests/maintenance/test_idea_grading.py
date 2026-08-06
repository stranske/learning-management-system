"""Gate for idea-item grading and its fallback behavior.

The owner asked for answers to be graded rather than self-assessed, with a
way to push back when grading is poor. Two properties matter most here:

* grading runs through the LOCAL Claude Code CLI, never the Anthropic API,
  because work material may not leave the machine that way; and
* a review session never breaks when the grader is unavailable — it degrades
  to an honest, clearly-labelled fallback.
"""

from __future__ import annotations

import subprocess

import pytest

from lms.maintenance.grading import (
    ClaudeCodeGrader,
    KeyPoint,
    KeywordCoverageGrader,
    grade_idea_answer,
)
from lms.maintenance.seeds import ipo_surge_2026

KEY_POINTS = [
    KeyPoint.from_payload(raw) for raw in ipo_surge_2026.IDEA_ITEMS[0]["payload"]["key_points"]
]
PROMPT = ipo_surge_2026.IDEA_ITEMS[0]["prompt"]


class _StubGrader:
    """Stands in for the CLI with a fixed reply."""

    def __init__(self, result: object | None) -> None:
        self._result = result
        self.calls = 0

    def grade(self, *, prompt: str, answer: str, key_points: list[KeyPoint]) -> object | None:
        self.calls += 1
        return self._result


def test_grading_falls_back_when_no_grader_is_available() -> None:
    """An unavailable grader must not break the review loop."""
    stub = _StubGrader(None)

    result = grade_idea_answer(
        prompt=PROMPT,
        answer="Dollar volume is a record but the number of IPOs is near normal.",
        key_points=KEY_POINTS,
        grader=stub,
    )

    assert stub.calls == 1
    assert result.detail["grader"] == "keyword-coverage"
    # The learner is told the grade came from string matching, not judgment.
    assert "no grader available" in result.explanation.lower()


def test_fallback_scores_on_required_points_only() -> None:
    """Optional points must not drag down a complete answer."""
    grader = KeywordCoverageGrader()

    complete = grader.grade(
        prompt=PROMPT,
        answer=(
            "Dollar volume is at a record but the number of IPOs is near its long-run "
            "norm; the record is amplified by a few very large deals; and IPO valuations "
            "are only modestly above their long-run median, well below prior booms."
        ),
        key_points=KEY_POINTS,
    )
    empty = grader.grade(prompt=PROMPT, answer="No idea.", key_points=KEY_POINTS)

    assert complete.score == pytest.approx(1.0)
    assert complete.passed
    assert empty.score == 0.0
    assert not empty.passed


def test_fallback_names_what_was_missed() -> None:
    """Feedback should say which point was absent, not just give a number."""
    result = KeywordCoverageGrader().grade(
        prompt=PROMPT,
        answer="The dollar volume is a record but the number of IPOs is near normal.",
        key_points=KEY_POINTS,
    )

    assert 0.0 < result.score < 1.0
    assert result.detail["missed"]
    assert "Missed:" in result.explanation


def test_claude_code_grader_parses_a_json_verdict(monkeypatch: pytest.MonkeyPatch) -> None:
    """The CLI's JSON reply becomes a coverage score."""
    grader = ClaudeCodeGrader()
    monkeypatch.setattr("lms.maintenance.grading.shutil.which", lambda _: "/usr/local/bin/claude")

    def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        assert cmd[0] == "claude"
        assert cmd[1] == "-p", "must use headless print mode"
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout='Here you go: {"covered": [1, 2, 3], "explanation": "Solid coverage."}',
            stderr="",
        )

    monkeypatch.setattr("lms.maintenance.grading.subprocess.run", fake_run)

    result = grader.grade(prompt=PROMPT, answer="...", key_points=KEY_POINTS)

    assert result is not None
    assert result.score == pytest.approx(1.0)
    assert result.detail["grader"] == "claude-code"
    assert result.explanation == "Solid coverage."


def test_claude_code_grader_returns_none_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Timeouts, non-zero exits and garbage output all degrade, never raise."""
    grader = ClaudeCodeGrader()
    monkeypatch.setattr("lms.maintenance.grading.shutil.which", lambda _: "/usr/local/bin/claude")

    def timeout_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        raise subprocess.TimeoutExpired(cmd, 60)

    monkeypatch.setattr("lms.maintenance.grading.subprocess.run", timeout_run)
    assert grader.grade(prompt=PROMPT, answer="x", key_points=KEY_POINTS) is None

    monkeypatch.setattr(
        "lms.maintenance.grading.subprocess.run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, stdout="", stderr="boom"),
    )
    assert grader.grade(prompt=PROMPT, answer="x", key_points=KEY_POINTS) is None

    monkeypatch.setattr(
        "lms.maintenance.grading.subprocess.run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, stdout="not json at all", stderr=""),
    )
    assert grader.grade(prompt=PROMPT, answer="x", key_points=KEY_POINTS) is None


def test_missing_cli_is_reported_as_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("lms.maintenance.grading.shutil.which", lambda _: None)
    grader = ClaudeCodeGrader()

    assert not grader.available()
    assert grader.grade(prompt=PROMPT, answer="x", key_points=KEY_POINTS) is None


def test_grading_prompt_asks_for_coverage_not_a_holistic_mark(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A coverage vector is what the learner can argue with and the scheduler can use."""
    captured: dict[str, str] = {}
    monkeypatch.setattr("lms.maintenance.grading.shutil.which", lambda _: "/bin/claude")

    def capture(cmd, **kwargs):  # type: ignore[no-untyped-def]
        captured["instruction"] = cmd[2]
        return subprocess.CompletedProcess(cmd, 0, stdout='{"covered": []}', stderr="")

    monkeypatch.setattr("lms.maintenance.grading.subprocess.run", capture)
    ClaudeCodeGrader().grade(prompt=PROMPT, answer="answer", key_points=KEY_POINTS)

    instruction = captured["instruction"]
    assert "COVERS each key point" in instruction
    assert "Ignore wording" in instruction
    # Every key point must be listed for the grader to judge against.
    for point in KEY_POINTS:
        assert point.label in instruction


def test_seed_idea_items_all_declare_required_points() -> None:
    """A drafted idea item with no required point could never be failed."""
    for item in ipo_surge_2026.IDEA_ITEMS:
        points = [KeyPoint.from_payload(raw) for raw in item["payload"]["key_points"]]
        assert any(p.required for p in points), item["title"]
