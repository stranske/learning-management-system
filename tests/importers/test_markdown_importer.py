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


def test_nested_subsection_points_to_parent_as_prerequisite(
    db_session: Session, tmp_path: Path
) -> None:
    """A nested H2 subsection has its H1 section as a prerequisite, not vice versa.

    Canonical direction (see ``KnowledgeEdge``) is source -> target meaning
    "source has prerequisite target". A subsection depends on the section that
    contains it, so the subsection is the edge source and the parent section is
    the target the learner must cover first. This is the same orientation the
    CSV importer uses (source=node, target=its listed prerequisite).
    """
    note = _write_note(tmp_path)

    import_markdown_notes(db_session, note, actor_id="user:alice")
    db_session.commit()

    title_by_id = {node.id: node.title for node in db_session.query(KnowledgeNode).all()}
    edges = db_session.query(KnowledgeEdge).all()
    assert len(edges) == 2

    directed = {
        (title_by_id[edge.source_node_id], title_by_id[edge.target_node_id]) for edge in edges
    }
    # source (dependent subsection) -> target (prerequisite parent section).
    assert directed == {
        ("Delayed Recall", "Retrieval Practice"),
        ("Transfer", "Retrieval Practice"),
    }
    # The parent section is always the prerequisite (target), never the source.
    assert all(title_by_id[edge.target_node_id] == "Retrieval Practice" for edge in edges)
    assert all(title_by_id[edge.source_node_id] != "Retrieval Practice" for edge in edges)


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


def test_setext_headings_do_not_crash(db_session: Session, tmp_path: Path) -> None:
    note = tmp_path / "setext.md"
    note.write_text(
        "Big Title\n"
        "=========\n"
        "Intro text.\n"
        "\n"
        "Small Section\n"
        "-------------\n"
        "More details.\n",
        encoding="utf-8",
    )

    summary = import_markdown_notes(db_session, note, actor_id="user:alice")
    db_session.commit()

    assert summary.created_nodes == 2
    assert summary.created_edges == 1
    assert [node.title for node in db_session.query(KnowledgeNode).order_by(KnowledgeNode.title)] == [
        "Big Title",
        "Small Section",
    ]


def test_non_utf8_markdown_file_is_skipped_with_warning(
    db_session: Session, tmp_path: Path, caplog: Any
) -> None:
    note = tmp_path / "latin1.md"
    note.write_bytes("Café Notes\n==========\n".encode("latin-1"))

    summary = import_markdown_notes(db_session, note, dry_run=True)

    assert summary.dry_run is True
    assert summary.files_scanned == 0
    assert summary.planned_nodes == 0
    assert "skipping non-UTF-8 markdown file" in caplog.text


def test_import_records_audit_events_for_sources_nodes_and_edges(
    db_session: Session, tmp_path: Path
) -> None:
    note = _write_note(tmp_path)

    import_markdown_notes(
        db_session,
        note,
        source_visibility="local-only",
        actor_id="user:alice",
    )
    db_session.commit()

    audits = db_session.query(AuditLog).all()
    assert len(audits) == 8
    assert {row.action for row in audits} == {"create"}
    assert {row.actor_id for row in audits} == {"user:alice"}
    assert {row.source_subsystem for row in audits} == {"markdown-importer"}

    type_counts: dict[str, int] = {}
    for row in audits:
        type_counts[row.entity_type] = type_counts.get(row.entity_type, 0) + 1
    assert type_counts == {
        "SourceReference": 3,
        "KnowledgeNode": 3,
        "KnowledgeEdge": 2,
    }


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
    assert "planned creates:" in out


def test_multi_file_import_links_subsections_within_their_own_file(
    db_session: Session, tmp_path: Path
) -> None:
    """Regression: each H2's prerequisite edge points at the H1 in its OWN file.

    Before the per-file ``parent_index`` rebasing fix, the index was file-local
    but applied to a node list accumulated globally across files, so the second
    file's subsections linked to a node in the first file. With two files we get
    a cross-file mislink (Beta Two -> Alpha One) unless the index is rebased.
    """
    (tmp_path / "a.md").write_text(
        "# Alpha One\nAlpha intro.\n\n## Alpha Two\nAlpha subsection.\n",
        encoding="utf-8",
    )
    (tmp_path / "b.md").write_text(
        "# Beta One\nBeta intro.\n\n## Beta Two\nBeta subsection.\n",
        encoding="utf-8",
    )

    summary = import_markdown_notes(db_session, tmp_path, actor_id="user:alice")
    db_session.commit()

    assert summary.created_nodes == 4
    assert summary.created_edges == 2

    title_by_id = {node.id: node.title for node in db_session.query(KnowledgeNode).all()}
    directed = {
        (title_by_id[edge.source_node_id], title_by_id[edge.target_node_id])
        for edge in db_session.query(KnowledgeEdge).all()
    }
    # Each subsection links to the H1 in its own file — never across files.
    assert directed == {
        ("Alpha Two", "Alpha One"),
        ("Beta Two", "Beta One"),
    }
