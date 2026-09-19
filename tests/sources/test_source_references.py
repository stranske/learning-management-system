"""SourceReference model and repository tests."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from lms.audit.models import AuditLog
from lms.sources.models import (
    DRIFT_STATUSES,
    MULTI_SOURCE_ROLES,
    SOURCE_TYPES,
    SOURCE_VISIBILITIES,
    SourceReference,
)
from lms.sources.repository import (
    _select_passage,
    compute_source_hash,
    create_source_reference,
    update_source_reference,
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


def _source_kwargs(**changes: Any) -> dict[str, Any]:
    return {
        "source_type": "internal-note",
        "stable_locator": "note:enum-test",
        "actor_id": "user:alice",
        "content": "source text",
        **changes,
    }


@pytest.mark.parametrize(
    ("field", "value", "allowed"),
    [
        ("source_type", "invalid", SOURCE_TYPES),
        ("source_visibility", "hidden", SOURCE_VISIBILITIES),
        ("multi_source_role", "invalid", MULTI_SOURCE_ROLES),
        ("source_type", "", SOURCE_TYPES),
        ("source_visibility", "", SOURCE_VISIBILITIES),
        ("multi_source_role", "", MULTI_SOURCE_ROLES),
        ("source_type", None, SOURCE_TYPES),
        ("source_visibility", None, SOURCE_VISIBILITIES),
    ],
)
@pytest.mark.parametrize("prehashed", [False, True])
def test_create_rejects_source_enums_before_persistence(
    db_session: Session, field: str, value: object, allowed: tuple[str, ...], prehashed: bool
) -> None:
    kwargs = _source_kwargs(**{field: value})
    if prehashed:
        kwargs["content_hash"] = "precomputed"
    with pytest.raises(ValueError, match=field) as error:
        create_source_reference(db_session, **kwargs)
    assert f"expected one of {allowed}" in str(error.value)
    assert db_session.is_active
    assert not db_session.new
    db_session.commit()
    assert db_session.query(SourceReference).count() == 0
    assert db_session.query(AuditLog).count() == 0
    create_source_reference(db_session, **_source_kwargs())
    db_session.commit()
    assert db_session.query(SourceReference).count() == 1
    assert db_session.query(AuditLog).count() == 1


@pytest.mark.parametrize(
    ("field", "value", "allowed"),
    [
        ("source_type", "invalid", SOURCE_TYPES),
        ("source_visibility", "hidden", SOURCE_VISIBILITIES),
        ("drift_status", "unknown", DRIFT_STATUSES),
        ("multi_source_role", "invalid", MULTI_SOURCE_ROLES),
        ("source_type", "", SOURCE_TYPES),
        ("source_visibility", "", SOURCE_VISIBILITIES),
        ("drift_status", "", DRIFT_STATUSES),
        ("multi_source_role", "", MULTI_SOURCE_ROLES),
    ],
)
def test_update_rejects_source_enums_before_any_mutation(
    db_session: Session, field: str, value: str, allowed: tuple[str, ...]
) -> None:
    reference = create_source_reference(db_session, **_source_kwargs())
    db_session.commit()
    old_value, old_hash = getattr(reference, field), reference.content_hash
    with pytest.raises(ValueError, match=field) as error:
        update_source_reference(
            db_session,
            reference,
            actor_id="user:alice",
            stable_locator="must-not-persist",
            content="must-not-be-hashed",
            **{field: value},
        )
    assert f"expected one of {allowed}" in str(error.value)
    assert db_session.is_active
    assert not db_session.dirty
    db_session.commit()
    db_session.refresh(reference)
    assert reference.stable_locator == "note:enum-test"
    assert reference.content_hash == old_hash
    assert getattr(reference, field) == old_value
    assert db_session.query(AuditLog).count() == 1
    update_source_reference(db_session, reference, actor_id="user:alice", drift_status="stale")
    db_session.commit()
    assert reference.drift_status == "stale"
    assert db_session.query(AuditLog).count() == 2


@pytest.mark.parametrize(
    ("field", "value"),
    [("source_type", value) for value in SOURCE_TYPES]
    + [("source_visibility", value) for value in SOURCE_VISIBILITIES]
    + [("multi_source_role", value) for value in (*MULTI_SOURCE_ROLES, None)],
)
def test_create_accepts_each_source_enum(
    db_session: Session, field: str, value: str | None
) -> None:
    reference = create_source_reference(
        db_session, **_source_kwargs(content_hash="precomputed", **{field: value})
    )
    db_session.commit()
    assert getattr(reference, field) == value


@pytest.mark.parametrize(
    ("field", "value"),
    [("source_type", value) for value in SOURCE_TYPES]
    + [("source_visibility", value) for value in SOURCE_VISIBILITIES]
    + [("multi_source_role", value) for value in MULTI_SOURCE_ROLES]
    + [("drift_status", value) for value in DRIFT_STATUSES],
)
def test_update_accepts_each_source_enum(db_session: Session, field: str, value: str) -> None:
    reference = create_source_reference(db_session, **_source_kwargs())
    update_source_reference(db_session, reference, actor_id="user:alice", **{field: value})
    db_session.commit()
    assert getattr(reference, field) == value


def test_update_preserves_none_as_no_change(db_session: Session) -> None:
    reference = create_source_reference(db_session, **_source_kwargs(multi_source_role="primary"))
    update_source_reference(
        db_session,
        reference,
        actor_id="user:alice",
        source_type=None,
        source_visibility=None,
        drift_status=None,
        multi_source_role=None,
    )
    db_session.commit()
    assert reference.source_type == "internal-note"
    assert reference.source_visibility == "public"
    assert reference.drift_status == "current"
    assert reference.multi_source_role == "primary"
