"""SourceReference model and repository tests."""

from __future__ import annotations

import hashlib

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from lms.audit.models import AuditLog
from lms.sources.models import SourceReference
from lms.sources.repository import compute_source_hash, create_source_reference


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


def test_compute_source_hash_uses_markdown_line_range(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Markdown hashes can target a stable 1-based line range."""
    note = tmp_path / "note.md"
    note.write_text("# Title\nfirst passage\nsecond passage\n", encoding="utf-8")

    digest = compute_source_hash(markdown_path=note, passage_range="L2-L2")

    assert digest == hashlib.sha256(b"first passage\n").hexdigest()


def test_source_references_table_is_created_by_base_metadata(db_session: Session) -> None:
    """``Base.metadata.create_all`` creates the source reference table."""
    bind = db_session.bind
    assert bind is not None
    inspector = inspect(bind)
    assert "source_references" in inspector.get_table_names()
