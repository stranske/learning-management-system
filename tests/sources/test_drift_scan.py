"""Drift scanning tests for markdown-backed source references."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from lms.audit.models import AuditLog
from lms.sources.repository import (
    compute_source_hash_for_reference,
    create_source_reference,
    scan_source_references,
)


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


def test_freetext_passage_range_not_false_stale(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """Free-text markdown ranges use the same hash basis at create and scan time."""
    note = tmp_path / "research.md"
    note.write_text("# Heading\npassage body\nappendix\n", encoding="utf-8")
    reference = create_source_reference(
        db_session,
        source_type="markdown-file",
        stable_locator=str(note),
        passage_range="Section 1",
        content="passage body",
        actor_id="user:alice",
    )
    db_session.commit()

    summary = scan_source_references(db_session, actor_id="system:test")
    db_session.commit()

    assert summary.scanned == 1
    assert summary.current == 1
    assert summary.stale == 0
    assert reference.drift_status == "current"


def test_changed_internal_note_marks_reference_stale(db_session: Session) -> None:
    """A changed internal-note (re-derived via resolver) flips to stale + audits."""
    reference = create_source_reference(
        db_session,
        source_type="internal-note",
        stable_locator="note://research/calibration",
        content="original note body",
        actor_id="user:alice",
    )
    db_session.commit()

    # The note's content is not persisted on the model, so the scan re-derives it
    # via an injected resolver (here returning the changed body).
    summary = scan_source_references(
        db_session,
        actor_id="system:test",
        note_resolver=lambda ref: "changed note body",
    )
    db_session.commit()

    assert summary.scanned == 1
    assert summary.stale == 1
    assert summary.skipped == 0
    assert reference.drift_status == "stale"
    audit = (
        db_session.query(AuditLog).filter_by(entity_id=reference.id, action="drift-status").one()
    )
    assert audit.before_summary["drift_status"] == "current"
    assert audit.after_summary["drift_status"] == "stale"


def test_internal_note_unchanged_stays_current(db_session: Session) -> None:
    """An internal-note whose re-derived content matches stays current."""
    reference = create_source_reference(
        db_session,
        source_type="internal-note",
        stable_locator="note://research/stable",
        content="stable note body",
        actor_id="user:alice",
    )
    db_session.commit()

    summary = scan_source_references(
        db_session,
        actor_id="system:test",
        note_resolver=lambda ref: "stable note body",
    )
    db_session.commit()

    assert summary.scanned == 1
    assert summary.current == 1
    assert reference.drift_status == "current"


def test_internal_note_without_resolver_is_skipped_not_scanned(db_session: Session) -> None:
    """Without a resolver an internal-note is reported as skipped, never scanned."""
    create_source_reference(
        db_session,
        source_type="internal-note",
        stable_locator="note://research/unresolved",
        content="body",
        actor_id="user:alice",
    )
    db_session.commit()

    summary = scan_source_references(db_session, actor_id="system:test")
    db_session.commit()

    assert summary.scanned == 0
    assert summary.skipped == 1


def test_url_reference_marks_stale_with_injected_fetcher(db_session: Session) -> None:
    """A url reference flips to stale when the fetched content changes (no live net)."""
    reference = create_source_reference(
        db_session,
        source_type="url",
        stable_locator="https://example.org/source",
        content="<html>v1</html>",
        actor_id="user:alice",
    )
    db_session.commit()

    summary = scan_source_references(
        db_session,
        actor_id="system:test",
        allow_network=True,
        url_fetcher=lambda url: "<html>v2</html>",
    )
    db_session.commit()

    assert summary.scanned == 1
    assert summary.stale == 1
    assert reference.drift_status == "stale"


def test_url_not_fetched_when_network_disabled(db_session: Session) -> None:
    """With allow_network=False the url fetcher is never called; counted separately."""

    def _forbidden_fetcher(url: str) -> str:
        raise AssertionError(f"network must stay off, but fetched {url!r}")

    reference = create_source_reference(
        db_session,
        source_type="url",
        stable_locator="https://example.org/source",
        content="<html>v1</html>",
        actor_id="user:alice",
    )
    db_session.commit()

    summary = scan_source_references(
        db_session,
        actor_id="system:test",
        url_fetcher=_forbidden_fetcher,
    )
    db_session.commit()

    assert summary.scanned == 0
    assert summary.network_skipped == 1
    assert reference.drift_status == "current"


def test_pdf_and_kindle_counted_as_explicit_unsupported(db_session: Session) -> None:
    """pdf-passage and kindle-highlight get distinct unsupported_* reasons."""
    create_source_reference(
        db_session,
        source_type="pdf-passage",
        stable_locator="library://book.pdf",
        content="page text",
        actor_id="user:alice",
    )
    create_source_reference(
        db_session,
        source_type="kindle-highlight",
        stable_locator="kindle://highlight/1",
        content="highlight text",
        actor_id="user:alice",
    )
    db_session.commit()

    summary = scan_source_references(db_session, actor_id="system:test")
    db_session.commit()

    assert summary.unsupported_pdf == 1
    assert summary.unsupported_kindle == 1
    assert summary.scanned == 0
    assert summary.skipped == 0


def test_url_reference_stays_current_when_fetched_content_unchanged(db_session: Session) -> None:
    """A url whose fetched content hash matches stays current."""
    reference = create_source_reference(
        db_session,
        source_type="url",
        stable_locator="https://example.org/stable",
        content="<html>v1</html>",
        actor_id="user:alice",
    )
    db_session.commit()

    summary = scan_source_references(
        db_session,
        actor_id="system:test",
        allow_network=True,
        url_fetcher=lambda url: "<html>v1</html>",
    )
    db_session.commit()

    assert summary.scanned == 1
    assert summary.current == 1
    assert reference.drift_status == "current"


def test_url_fetcher_exception_marks_reference_missing(db_session: Session) -> None:
    """When the url fetcher raises the reference is marked missing (unreachable URL)."""
    reference = create_source_reference(
        db_session,
        source_type="url",
        stable_locator="https://example.org/gone",
        content="<html>v1</html>",
        actor_id="user:alice",
    )
    db_session.commit()

    def _broken_fetcher(url: str) -> str:
        raise ConnectionError("unreachable")

    summary = scan_source_references(
        db_session,
        actor_id="system:test",
        allow_network=True,
        url_fetcher=_broken_fetcher,
    )
    db_session.commit()

    assert summary.scanned == 1
    assert summary.missing == 1
    assert reference.drift_status == "missing"


def test_compute_source_hash_for_reference_raises_for_internal_note_without_content() -> None:
    """compute_source_hash_for_reference raises a clear ValueError for internal-note without content."""
    with pytest.raises(ValueError, match="internal-note.*require.*resolved content"):
        compute_source_hash_for_reference(
            source_type="internal-note",
            stable_locator="note://research/x",
            passage_range=None,
            content=None,
            hash_algorithm="sha256",
        )


def test_compute_source_hash_for_reference_raises_for_url_without_content() -> None:
    """compute_source_hash_for_reference raises a clear ValueError for url without content."""
    with pytest.raises(ValueError, match="url.*require.*resolved content"):
        compute_source_hash_for_reference(
            source_type="url",
            stable_locator="https://example.org/page",
            passage_range=None,
            content=None,
            hash_algorithm="sha256",
        )
