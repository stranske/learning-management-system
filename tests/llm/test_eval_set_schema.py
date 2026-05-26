"""Schema validity and replay smoke tests for the LLM eval gold sets."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lms.llm.budgets import DailyBudgetTracker
from lms.llm.client import LLMClient
from lms.llm.config import DEFAULT_MODE_MODELS, LLMConfig
from lms.llm.eval_sets import (
    ALLOWED_EXPECTED_LABELS,
    ALLOWED_SCENARIOS,
    EvalSetError,
    load_eval_set,
    replay_eval_set,
    score_labels,
)
from lms.llm.providers import FakeProvider

REPO_ROOT = Path(__file__).resolve().parents[2]
STUDY_COACH_V1 = REPO_ROOT / "docs" / "llm" / "eval-sets" / "study-coach-v1.jsonl"

_REQUIRED_SCENARIOS = (
    "answer-seeking",
    "confusion-repair",
    "retrieval-prompt",
    "hint-overuse",
    "high-confidence-weak-evidence",
    "direct-explanation",
)


def _build_client() -> LLMClient:
    return LLMClient(
        config=LLMConfig(
            mode_models=dict(DEFAULT_MODE_MODELS),
            global_daily_cap_micro_usd=1_000_000,
            default_provider="fake",
        ),
        providers={"fake": FakeProvider()},
        budget=DailyBudgetTracker(mode_caps_micro_usd={}, global_cap_micro_usd=1_000_000),
    )


def test_study_coach_gold_set_schema_valid() -> None:
    """The shipped study-coach-v1 gold set must load and meet the contract."""
    entries = load_eval_set(STUDY_COACH_V1)

    assert len(entries) >= 10
    ids = [entry.entry_id for entry in entries]
    assert len(set(ids)) == len(ids), "entry ids must be unique"

    covered_scenarios = {entry.scenario for entry in entries}
    missing = set(_REQUIRED_SCENARIOS) - covered_scenarios
    assert not missing, (
        f"study-coach-v1 must cover the six required scenarios from the issue; "
        f"missing: {sorted(missing)}"
    )
    assert covered_scenarios <= set(ALLOWED_SCENARIOS)

    for entry in entries:
        assert entry.expected_labels, f"{entry.entry_id} must have expected_labels"
        assert set(entry.expected_labels) <= set(ALLOWED_EXPECTED_LABELS)
        assert entry.prompt.strip(), f"{entry.entry_id} prompt must be non-empty"
        assert entry.mode in ("study-coach", "practice", "transfer", "authoring-assist")
        assert entry.trace_class in ("ephemeral", "formative", "evidence-grade")


def test_load_eval_set_rejects_unknown_field(tmp_path: Path) -> None:
    payload = {
        "entry_id": "tmp-1",
        "scenario": "answer-seeking",
        "mode": "study-coach",
        "trace_class": "ephemeral",
        "prompt": "x",
        "expected_labels": ["asks_for_retrieval"],
        "bogus_field": True,
    }
    target = tmp_path / "bogus.jsonl"
    target.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    with pytest.raises(EvalSetError, match="unknown field"):
        load_eval_set(target)


def test_load_eval_set_rejects_directory_paths(tmp_path: Path) -> None:
    with pytest.raises(EvalSetError, match="not a regular file"):
        load_eval_set(tmp_path)


def test_load_eval_set_rejects_whitespace_required_strings(tmp_path: Path) -> None:
    payload = {
        "entry_id": "tmp-1",
        "scenario": "answer-seeking",
        "mode": "study-coach",
        "trace_class": "ephemeral",
        "prompt": "   ",
        "expected_labels": ["asks_for_retrieval"],
    }
    target = tmp_path / "blank-prompt.jsonl"
    target.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    with pytest.raises(EvalSetError, match="field 'prompt' must be a non-empty string"):
        load_eval_set(target)


def test_load_eval_set_rejects_duplicate_entry_ids(tmp_path: Path) -> None:
    row = {
        "entry_id": "tmp-1",
        "scenario": "answer-seeking",
        "mode": "study-coach",
        "trace_class": "ephemeral",
        "prompt": "x",
        "expected_labels": ["asks_for_retrieval"],
    }
    target = tmp_path / "dupes.jsonl"
    target.write_text(json.dumps(row) + "\n" + json.dumps(row) + "\n", encoding="utf-8")

    with pytest.raises(EvalSetError, match="duplicate entry_id"):
        load_eval_set(target)


def test_load_eval_set_rejects_unknown_expected_label(tmp_path: Path) -> None:
    payload = {
        "entry_id": "tmp-1",
        "scenario": "answer-seeking",
        "mode": "study-coach",
        "trace_class": "ephemeral",
        "prompt": "x",
        "expected_labels": ["asks_for_retrieval", "not-a-real-label"],
    }
    target = tmp_path / "bad-label.jsonl"
    target.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    with pytest.raises(EvalSetError, match="unknown labels"):
        load_eval_set(target)


def test_load_eval_set_ignores_blank_and_comment_lines(tmp_path: Path) -> None:
    row = {
        "entry_id": "tmp-1",
        "scenario": "answer-seeking",
        "mode": "study-coach",
        "trace_class": "ephemeral",
        "prompt": "x",
        "expected_labels": ["asks_for_retrieval"],
    }
    contents = "# header comment\n\n" + json.dumps(row) + "\n\n# trailing\n"
    target = tmp_path / "with-comments.jsonl"
    target.write_text(contents, encoding="utf-8")

    entries = load_eval_set(target)
    assert len(entries) == 1
    assert entries[0].entry_id == "tmp-1"


def test_score_labels_uses_canonical_label_keywords() -> None:
    text = "Try to remember the periodic table without looking. Next step: read aloud."
    matched, missing = score_labels(
        text, expected_labels=("asks_for_retrieval", "offers_next_action")
    )
    assert set(matched) == {"asks_for_retrieval", "offers_next_action"}
    assert not missing


def test_replay_eval_set_isolates_eval_traffic_from_production_budget() -> None:
    """Replay must not record traffic on the production budget tracker.

    This is the privacy/cost invariant from the project plan: regression sweeps
    must not exhaust the daily kill-switch budget.
    """
    entries = load_eval_set(STUDY_COACH_V1)
    client = _build_client()

    pre_global = client.budget.spent_micro_usd()

    outcomes = replay_eval_set(client, entries[:3])

    assert len(outcomes) == 3
    for outcome in outcomes:
        assert outcome.response.session.is_replay is True
        assert outcome.response.session.external_export_allowed is False

    assert client.budget.spent_micro_usd() == pre_global
