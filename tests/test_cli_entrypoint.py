"""Tests for the LMS module entrypoint."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.exc import SQLAlchemyError

import lms.__main__ as lms_main
from lms.importers.csv_graph import CsvGraphImportError
from lms.llm.client import LLMClient
from lms.llm.config import DEFAULT_MODE_MODELS
from lms.llm.eval_sets import EvalSetEntry, ReplayOutcome, replay_eval_set
from lms.llm.exceptions import BudgetExceeded
from lms.sources.repository import DriftScanSummary


def test_main_starts_uvicorn(monkeypatch: Any) -> None:
    calls: list[dict[str, object]] = []

    def fake_run(app: str, **kwargs: object) -> None:
        calls.append({"app": app, **kwargs})

    monkeypatch.setattr("uvicorn.run", fake_run)
    monkeypatch.setattr("sys.argv", ["lms"])

    lms_main.main()

    assert calls == [
        {
            "app": "lms.main:app",
            "host": "127.0.0.1",
            "port": 8000,
            "reload": True,
        }
    ]


def test_import_notes_defaults_source_visibility_to_local_only(
    monkeypatch: Any, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}

    class StubSummary:
        def to_cli_summary_lines(self) -> list[str]:
            return ["ok"]

    def fake_import_markdown_notes(
        session: object,
        path: Path,
        *,
        limit: int | None = None,
        dry_run: bool = False,
        scope: str = "personal",
        source_visibility: str = "local-only",
        actor_id: str = "system:import-notes",
    ) -> StubSummary:
        captured.update(
            {
                "session": session,
                "path": path,
                "limit": limit,
                "dry_run": dry_run,
                "scope": scope,
                "source_visibility": source_visibility,
                "actor_id": actor_id,
            }
        )
        return StubSummary()

    note = tmp_path / "research.md"
    note.write_text("# Title\n", encoding="utf-8")

    monkeypatch.setattr(lms_main, "import_markdown_notes", fake_import_markdown_notes)
    monkeypatch.setattr("sys.argv", ["lms", "import-notes", str(note), "--dry-run"])

    lms_main.main()

    assert captured["source_visibility"] == "local-only"


def test_import_notes_accepts_source_visibility_override(monkeypatch: Any, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    class StubSummary:
        def to_cli_summary_lines(self) -> list[str]:
            return ["ok"]

    def fake_import_markdown_notes(
        session: object,
        path: Path,
        *,
        limit: int | None = None,
        dry_run: bool = False,
        scope: str = "personal",
        source_visibility: str = "local-only",
        actor_id: str = "system:import-notes",
    ) -> StubSummary:
        captured["source_visibility"] = source_visibility
        return StubSummary()

    note = tmp_path / "research.md"
    note.write_text("# Title\n", encoding="utf-8")

    monkeypatch.setattr(lms_main, "import_markdown_notes", fake_import_markdown_notes)
    monkeypatch.setattr(
        "sys.argv",
        ["lms", "import-notes", str(note), "--dry-run", "--source-visibility", "public"],
    )

    lms_main.main()

    assert captured["source_visibility"] == "public"


@dataclass(frozen=True)
class _FakeSummary:
    nodes: int
    edges: int
    source_references: int
    dry_run: bool


def test_import_graph_calls_importer_and_prints_summary(
    monkeypatch: Any, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    calls: list[dict[str, object]] = []
    csv_path = tmp_path / "graph.csv"
    csv_path.write_text(
        "title,knowledge_type,prerequisites,ownership_scope,status,source_locator\n",
        encoding="utf-8",
    )

    class _FakeSessionContext:
        def __enter__(self) -> object:
            return object()

        def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
            return None

    def fake_import(session: object, path: Path, *, dry_run: bool, actor_id: str) -> _FakeSummary:
        calls.append(
            {
                "session": session,
                "path": path,
                "dry_run": dry_run,
                "actor_id": actor_id,
            }
        )
        return _FakeSummary(nodes=2, edges=1, source_references=2, dry_run=dry_run)

    monkeypatch.setattr(lms_main, "session_scope", lambda: _FakeSessionContext())
    monkeypatch.setattr(lms_main, "import_csv_graph", fake_import)
    monkeypatch.setattr(
        "sys.argv", ["lms", "import-graph", str(csv_path), "--dry-run", "--actor-id", "user:alice"]
    )

    lms_main.main()

    assert len(calls) == 1
    assert calls[0]["path"] == csv_path
    assert calls[0]["dry_run"] is True
    assert calls[0]["actor_id"] == "user:alice"
    assert capsys.readouterr().out.strip() == (
        "CSV graph import dry run: nodes=2 edges=1 source_references=2"
    )


def test_import_graph_exits_with_message_on_import_error(monkeypatch: Any, tmp_path: Path) -> None:
    csv_path = tmp_path / "graph.csv"
    csv_path.write_text(
        "title,knowledge_type,prerequisites,ownership_scope,status,source_locator\n",
        encoding="utf-8",
    )

    class _FakeSessionContext:
        def __enter__(self) -> object:
            return object()

        def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
            return None

    def fake_import(session: object, path: Path, *, dry_run: bool, actor_id: str) -> _FakeSummary:
        raise CsvGraphImportError("unknown prerequisite")

    monkeypatch.setattr(lms_main, "session_scope", lambda: _FakeSessionContext())
    monkeypatch.setattr(lms_main, "import_csv_graph", fake_import)
    monkeypatch.setattr("sys.argv", ["lms", "import-graph", str(csv_path)])

    with pytest.raises(SystemExit, match="CSV graph import failed: unknown prerequisite"):
        lms_main.main()


@pytest.mark.parametrize("api_key", [None, "test-key-unused"])
@pytest.mark.parametrize(
    "policy_env, expected_cap, override_model",
    [
        ({"LLM_DAILY_CAP_MICRO_USD": "12345", "LLM_DAILY_BUDGET_USD": "9"}, 12345, True),
        ({"LLM_DAILY_BUDGET_USD": "0.025"}, 25000, True),
        ({}, 200000, False),
    ],
)
def test_authoring_assist_uses_environment_llm_config(
    monkeypatch: Any,
    capsys: pytest.CaptureFixture[str],
    api_key: str | None,
    policy_env: dict[str, str],
    expected_cap: int,
    override_model: bool,
) -> None:
    """authoring-assist propose routes through propose_authoring_drafts and prints ids."""

    class _FakeLLMProposal:
        id = "proposal-1"
        llm_model = "fake-authoring-model"

    class _FakeKnowledgeNode:
        id = "node-1"

    class _FakePrompt:
        id = "prompt-1"

    class _FakeResult:
        llm_proposal = _FakeLLMProposal()
        knowledge_node = _FakeKnowledgeNode()
        knowledge_edge = None
        prompt = _FakePrompt()

    for key in ("LLM_DAILY_CAP_MICRO_USD", "LLM_DAILY_BUDGET_USD", "LLM_MODEL_AUTHORING_ASSIST"):
        monkeypatch.delenv(key, raising=False)
    for key, value in policy_env.items():
        monkeypatch.setenv(key, value)
    if override_model:
        monkeypatch.setenv("LLM_MODEL_AUTHORING_ASSIST", "operator-authoring-model")
    monkeypatch.setenv("LLM_DEFAULT_PROVIDER", "anthropic")
    monkeypatch.setattr(
        lms_main, "get_settings", lambda: SimpleNamespace(anthropic_api_key=api_key)
    )
    expected_model = (
        "operator-authoring-model"
        if override_model
        else ("claude-haiku-4-5" if api_key else "fake-authoring-model")
    )
    calls: list[dict[str, object]] = []

    def fake_propose(session: object, *, client: LLMClient, **kwargs: object) -> _FakeResult:
        assert client.config.model_for("authoring-assist") == expected_model
        assert client.config.default_provider == ("anthropic" if api_key else "fake")
        assert client.config.global_daily_cap_micro_usd == expected_cap
        assert client.budget.global_cap_micro_usd == expected_cap
        with pytest.raises(BudgetExceeded):
            client.budget.preflight("authoring-assist", expected_cap + 1)
        calls.append(kwargs)
        return _FakeResult()

    class _FakeSessionContext:
        def __enter__(self) -> object:
            return object()

        def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
            pass

    monkeypatch.setattr(lms_main, "session_scope", lambda: _FakeSessionContext())
    monkeypatch.setattr(lms_main, "propose_authoring_drafts", fake_propose)
    monkeypatch.setattr(
        "sys.argv",
        [
            "lms",
            "authoring-assist",
            "propose",
            "--source-reference",
            "src-1",
            "--target-node",
            "node-1",
            "--learning-goal",
            "goal-1",
            "--actor-id",
            "user:alice",
            "--related-node-title",
            "Test Node",
            "--related-node-knowledge-type",
            "conceptual",
            "--prompt-body",
            "Explain X",
            "--prompt-knowledge-type",
            "conceptual",
            "--prompt-cognitive-action",
            "explain",
            "--prompt-demand-level",
            "medium",
            "--prompt-answer-form",
            "short-text",
        ],
    )

    lms_main.main()

    assert len(calls) == 1
    assert calls[0]["source_reference_id"] == "src-1"
    assert calls[0]["target_node_id"] == "node-1"
    assert calls[0]["learning_goal_id"] == "goal-1"
    assert calls[0]["actor_id"] == "user:alice"
    out = capsys.readouterr().out.strip()
    assert out.startswith("authoring-assist proposal complete:")
    assert "proposal=proposal-1" in out
    assert "node=node-1" in out
    assert "prompt=prompt-1" in out


def test_import_exits_with_message_on_database_error(monkeypatch: Any, tmp_path: Path) -> None:
    path = tmp_path / "import.jsonl"
    path.write_text("", encoding="utf-8")

    class _FakeSessionContext:
        def __enter__(self) -> object:
            return object()

        def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
            return None

    def fake_import_jsonl(session: object, path: Path, *, dry_run: bool) -> object:
        raise SQLAlchemyError("constraint failed")

    monkeypatch.setattr(lms_main, "session_scope", lambda: _FakeSessionContext())
    monkeypatch.setattr(lms_main, "import_jsonl", fake_import_jsonl)
    monkeypatch.setattr("sys.argv", ["lms", "import", str(path), "--apply"])

    with pytest.raises(SystemExit, match="import failed: constraint failed"):
        lms_main.main()


def test_source_references_scan_drift_prints_per_reason_breakdown(
    monkeypatch: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    """scan-drift subcommand invokes scan_source_references and prints all per-reason fields."""

    class _FakeSessionContext:
        def __enter__(self) -> object:
            return object()

        def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
            return None

    fake_summary = DriftScanSummary(
        scanned=5,
        current=3,
        stale=1,
        missing=1,
        skipped=2,
        unsupported_pdf=1,
        unsupported_kindle=1,
        network_skipped=3,
    )
    calls: list[dict[str, object]] = []

    def fake_scan(session: object, *, base_path: object, actor_id: str) -> DriftScanSummary:
        calls.append({"actor_id": actor_id, "base_path": base_path})
        return fake_summary

    monkeypatch.setattr(lms_main, "session_scope", lambda: _FakeSessionContext())
    monkeypatch.setattr(lms_main, "scan_source_references", fake_scan)
    monkeypatch.setattr(
        "sys.argv",
        ["lms", "source-references", "scan-drift", "--actor-id", "user:bob"],
    )

    lms_main.main()

    out = capsys.readouterr().out.strip()
    assert "scanned=5" in out
    assert "current=3" in out
    assert "stale=1" in out
    assert "missing=1" in out
    assert "skipped=2" in out
    assert "unsupported_pdf=1" in out
    assert "unsupported_kindle=1" in out
    assert "network_skipped=3" in out
    assert calls[0]["actor_id"] == "user:bob"


@pytest.mark.parametrize(
    "policy_env, expected_cap, expected_model",
    [
        (
            {"LLM_DAILY_CAP_MICRO_USD": "0", "LLM_MODEL_STUDY_COACH": "operator-coach"},
            0,
            "operator-coach",
        ),
        (
            {"LLM_DAILY_BUDGET_USD": "0.025", "LLM_MODEL_STUDY_COACH": "operator-coach"},
            25000,
            "operator-coach",
        ),
        ({}, 200000, DEFAULT_MODE_MODELS["study-coach"]),
    ],
)
def test_replay_eval_uses_environment_llm_config(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    policy_env: dict[str, str],
    expected_cap: int,
    expected_model: str,
) -> None:
    for key in ("LLM_DAILY_CAP_MICRO_USD", "LLM_DAILY_BUDGET_USD", "LLM_MODEL_STUDY_COACH"):
        monkeypatch.delenv(key, raising=False)
    for key, value in policy_env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("LLM_DEFAULT_PROVIDER", "anthropic")
    monkeypatch.setattr(lms_main, "get_settings", lambda: SimpleNamespace(anthropic_api_key=None))

    def refuse_production_session() -> None:
        pytest.fail("Replay opened a production database session")

    monkeypatch.setattr(lms_main, "session_scope", refuse_production_session)
    observed: list[ReplayOutcome] = []

    def capture_replay(
        client: LLMClient, entries: tuple[EvalSetEntry, ...]
    ) -> tuple[ReplayOutcome, ...]:
        assert client.config.default_provider == "fake"
        assert client.config.model_for("study-coach") == expected_model
        assert client.config.global_daily_cap_micro_usd == expected_cap
        assert client.budget.global_cap_micro_usd == expected_cap
        outcomes = replay_eval_set(client, entries)
        assert client.budget.spent_micro_usd() == 0
        assert client.budget.spent_micro_usd("study-coach") == 0
        observed.extend(outcomes)
        return outcomes

    monkeypatch.setattr(lms_main, "replay_eval_set", capture_replay)
    path = tmp_path / "eval.jsonl"
    path.write_text(
        json.dumps(
            {
                "entry_id": "policy-check",
                "scenario": "direct-explanation",
                "mode": "study-coach",
                "trace_class": "evidence-grade",
                "prompt": "Here is a concise explanation",
                "expected_labels": ["gives_direct_explanation"],
            }
        )
        + "\n"
    )
    monkeypatch.setattr("sys.argv", ["lms", "llm", "replay-eval", str(path)])

    lms_main.main()

    assert len(observed) == 1
    response = observed[0].response
    assert response.provider_response.model == expected_model
    assert response.provider_response.cost_micro_usd > 0
    assert response.session.is_replay is True
    assert response.session.external_export_allowed is False
    assert response.session.id is None  # transient ORM record, never persisted
    assert "replayed: 1 entries, 1 passed" in capsys.readouterr().out
