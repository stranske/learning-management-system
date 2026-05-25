"""Markdown importer acceptance tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

import lms.__main__ as lms_main
from lms.audit.models import AuditLog
from lms.graphs.models import KnowledgeEdge, KnowledgeNode
from lms.importers.markdown import import_markdown_notes
from lms.sources.models import SourceReference


def _write_note(tmp_path: Path) -> Path:
    note = tmp_path / "research.md"
    note.write_text(
        "# Retrieval Practice\n"
        "Trying to recall strengthens long-term memory.\n"
        "\n"
        "## Delayed Recall\n"
        "Delayed checks are better evidence than immediate fluency.\n"
        "\n"
        "## Transfer\n"
        "Use varied cases to test usable understanding.\n",
        encoding="utf-8",
    )
    return note


def test_h1_h2_create_draft_nodes_with_source_references(
    db_session: Session, tmp_path: Path
) -> None:
    note = _write_note(tmp_path)

    summary = import_markdown_notes(
        db_session,
        note,
        source_visibility="local-only",
        actor_id="user:alice",
    )
    db_session.commit()

    assert summary.created_nodes == 3
    assert summary.created_sources == 3
    assert summary.created_edges == 2

    nodes = db_session.query(KnowledgeNode).order_by(KnowledgeNode.title).all()
    assert {node.title for node in nodes} == {
        "Delayed Recall",
        "Retrieval Practice",
        "Transfer",
    }
    assert all(node.status == "draft" for node in nodes)
    assert all(node.provenance == "imported" for node in nodes)
    assert all(node.imported_from == str(note) for node in nodes)
    assert all(node.source_reference_id for node in nodes)

    references = db_session.query(SourceReference).all()
    assert len(references) == 3
    assert {reference.source_visibility for reference in references} == {"local-only"}
    assert {reference.source_type for reference in references} == {"markdown-file"}
    assert {reference.stable_locator for reference in references} == {str(note)}

    edges = db_session.query(KnowledgeEdge).all()
    assert len(edges) == 2
    assert {edge.edge_type for edge in edges} == {"prerequisite"}
    assert {edge.status for edge in edges} == {"draft"}

    audited_types = {row.entity_type for row in db_session.query(AuditLog).all()}
    assert {"SourceReference", "KnowledgeNode", "KnowledgeEdge"} <= audited_types


def test_dry_run_does_not_write_records(db_session: Session, tmp_path: Path) -> None:
    note = _write_note(tmp_path)

    summary = import_markdown_notes(db_session, note, dry_run=True)
    db_session.commit()

    assert summary.dry_run is True
    assert summary.planned_nodes == 3
    assert summary.planned_sources == 3
    assert summary.planned_edges == 2
    assert db_session.query(KnowledgeNode).count() == 0
    assert db_session.query(SourceReference).count() == 0
    assert db_session.query(KnowledgeEdge).count() == 0
    assert db_session.query(AuditLog).count() == 0


def test_cli_dry_run_reports_planned_nodes(monkeypatch: Any, tmp_path: Path, capsys: Any) -> None:
    note = _write_note(tmp_path)
    monkeypatch.setattr(
        "sys.argv",
        ["lms", "import-notes", str(note), "--limit", "10", "--dry-run"],
    )

    lms_main.main()

    out = capsys.readouterr().out
    assert "markdown import planned" in out
    assert "nodes=3" in out
    assert "sources=3" in out
