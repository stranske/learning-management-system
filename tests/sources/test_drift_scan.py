"""Drift scanning tests for markdown-backed source references."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from lms.audit.models import AuditLog
from lms.sources.repository import create_source_reference, scan_source_references


def test_changed_markdown_passage_marks_reference_stale(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """A changed markdown passage flips drift_status to stale and records audit."""
    note = tmp_path / "research.md"
    note.write_text("# Heading\noriginal passage\n", encoding="utf-8")
    reference = create_source_reference(
        db_session,
        source_type="markdown-file",
        stable_locator=str(note),
        passage_range="L2-L2",
        actor_id="user:alice",
    )
    db_session.commit()

    note.write_text("# Heading\nchanged passage\n", encoding="utf-8")
    summary = scan_source_references(db_session, actor_id="system:test")
    db_session.commit()

    assert summary.scanned == 1
    assert summary.stale == 1
    assert reference.drift_status == "stale"
    audit = (
        db_session.query(AuditLog).filter_by(entity_id=reference.id, action="drift-status").one()
    )
    assert audit.before_summary is not None
    assert audit.after_summary is not None
    assert audit.before_summary["drift_status"] == "current"
    assert audit.after_summary["drift_status"] == "stale"


def test_missing_markdown_file_marks_reference_missing(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """A missing markdown file flips drift_status to missing."""
    note = tmp_path / "missing.md"
    note.write_text("content\n", encoding="utf-8")
    reference = create_source_reference(
        db_session,
        source_type="markdown-file",
        stable_locator=str(note),
        actor_id="user:alice",
    )
    db_session.commit()
    note.unlink()

    summary = scan_source_references(db_session, actor_id="system:test")
    db_session.commit()

    assert summary.missing == 1
    assert reference.drift_status == "missing"
