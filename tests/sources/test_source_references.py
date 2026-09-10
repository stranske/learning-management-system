"""SourceReference model and repository tests."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from lms.audit.models import AuditLog
from lms.sources.models import SourceReference
from lms.sources.repository import (
    _select_passage,
    compute_source_hash,
    create_source_reference,
)


@pytest.mark.parametrize(
    ("passage_range", "expected"),
    [
        ("5-0", "one\ntwo\nthree\nfour\nfive\n"),
        ("5-1", "one\ntwo\nthree\nfour\nfive\n"),
        ("0-5", "one\ntwo\nthree\nfour\nfive\n"),
        ("L5-L0", "one\ntwo\nthree\nfour\nfive\n"),
        ("0-0", "one\n"),
        ("0", "one\n"),
        ("3-2", "two\nthree\n"),
        ("5-99", "five\nsix"),
        ("99-100", ""),
    ],
)
def test_passage_range_selection_and_hash(
    tmp_path: Path, passage_range: str, expected: str
) -> None:
    """Ordered and clamped ranges select and hash only the requested lines."""
    text = "one\ntwo\nthree\nfour\nfive\nsix"
    note = tmp_path / "note.md"
    note.write_text(text, encoding="utf-8")

    assert _select_passage(text, passage_range) == expected
    assert (
        compute_source_hash(markdown_path=note, passage_range=passage_range)
        == hashlib.sha256(expected.encode()).hexdigest()
    )


def test_create_source_reference_with_sha256_hash(db_session: Session) -> None:
    """Source references persist a stable sha256 hash and audit event."""
    reference = create_source_reference(
        db_session,
        source_type="internal-note",
        stable_locator="note:retrieval-practice",
        content="retrieval practice improves long-term retention",
        source_visibility="local-only",
        actor_id="user:alice",
    )
    db_session.commit()

    expected = hashlib.sha256(b"retrieval practice improves long-term retention").hexdigest()
    stored = db_session.get(SourceReference, reference.id)
    assert stored is not None
    assert stored.content_hash == expected
    assert stored.hash_algorithm == "sha256"
    assert stored.drift_status == "current"
    assert stored.source_visibility == "local-only"

    audit = db_session.query(AuditLog).filter_by(entity_id=reference.id).one()
    assert audit.entity_type == "SourceReference"
    assert audit.action == "create"
    assert audit.after_summary is not None
    assert audit.after_summary["content_hash"] == expected


def test_compute_source_hash_uses_markdown_line_range(tmp_path: Path) -> None:
    """Markdown hashes can target a stable 1-based line range."""
    note = tmp_path / "note.md"
    note.write_text("# Title\nfirst passage\nsecond passage\n", encoding="utf-8")

    digest = compute_source_hash(markdown_path=note, passage_range="L2-L2")

    assert digest == hashlib.sha256(b"first passage\n").hexdigest()


def test_create_markdown_reference_freetext_passage_range_hashes_whole_file(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """Create-time uses whole-file hashing for unparseable free-text ranges."""
    note = tmp_path / "research.md"
    note.write_text("# Heading\npassage scoped text\ntrailing context\n", encoding="utf-8")

    reference = create_source_reference(
        db_session,
        source_type="markdown-file",
        stable_locator=str(note),
        passage_range="Section 1",
        content="passage scoped text",
        actor_id="user:alice",
    )

    assert reference.content_hash == compute_source_hash(
        markdown_path=note, passage_range="Section 1"
    )


def test_source_references_table_is_created_by_base_metadata(db_session: Session) -> None:
    """``Base.metadata.create_all`` creates the source reference table."""
    bind = db_session.bind
    assert bind is not None
    inspector = inspect(bind)
    assert "source_references" in inspector.get_table_names()
