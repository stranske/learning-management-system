"""Tests for the LMS module entrypoint."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

import lms.__main__ as lms_main
from lms.importers.csv_graph import CsvGraphImportError


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
