"""Tests for the LMS module entrypoint."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import lms.__main__ as lms_main


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
        def to_cli_line(self) -> str:
            return "ok"

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
        def to_cli_line(self) -> str:
            return "ok"

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
