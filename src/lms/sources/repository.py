"""Repository helpers for SourceReference CRUD and drift scanning."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from lms.audit.repository import record_audit_event
from lms.sources.models import SourceReference

DEFAULT_HASH_ALGORITHM = "sha256"
_LINE_RANGE_PATTERN = re.compile(r"^(?:L|lines?:)?(?P<start>\d+)(?:[-:](?:L)?(?P<end>\d+))?$")


@dataclass(frozen=True)
class DriftScanSummary:
    """Summary of one drift-scan pass."""

    scanned: int
    current: int
    stale: int
    missing: int
    skipped: int


def compute_source_hash(
    content: str | bytes | None = None,
    *,
    markdown_path: str | Path | None = None,
    passage_range: str | None = None,
    hash_algorithm: str = DEFAULT_HASH_ALGORITHM,
    base_path: str | Path | None = None,
) -> str:
    """Compute a hash for explicit content or a markdown file passage."""
    hasher = hashlib.new(hash_algorithm)
    payload = _source_payload(
        content,
        markdown_path=markdown_path,
        passage_range=passage_range,
        base_path=base_path,
    )
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    hasher.update(payload)
    return hasher.hexdigest()


def create_source_reference(
    session: Session,
    *,
    source_type: str,
    stable_locator: str,
    actor_id: str,
    passage_range: str | None = None,
    content: str | bytes | None = None,
    content_hash: str | None = None,
    hash_algorithm: str = DEFAULT_HASH_ALGORITHM,
    source_visibility: str = "public",
    multi_source_role: str | None = None,
    source_subsystem: str = "api",
) -> SourceReference:
    """Create a source reference and record the authoring audit event."""
    resolved_hash = content_hash or compute_source_hash_for_reference(
        source_type=source_type,
        stable_locator=stable_locator,
        passage_range=passage_range,
        content=content,
        hash_algorithm=hash_algorithm,
    )
    reference = SourceReference(
        source_type=source_type,
        stable_locator=stable_locator,
        passage_range=passage_range,
        content_hash=resolved_hash,
        hash_algorithm=hash_algorithm,
        source_visibility=source_visibility,
        multi_source_role=multi_source_role,
    )
    session.add(reference)
    session.flush()
    record_audit_event(
        session,
        actor_id=actor_id,
        action="create",
        entity_type="SourceReference",
        entity_id=reference.id,
        source_subsystem=source_subsystem,
        after_summary=_reference_summary(reference),
    )
    return reference


def get_source_reference(session: Session, reference_id: str) -> SourceReference | None:
    """Return a source reference by stable id."""
    return session.get(SourceReference, reference_id)


def list_source_references(
    session: Session,
    *,
    source_type: str | None = None,
    drift_status: str | None = None,
    limit: int = 100,
) -> Sequence[SourceReference]:
    """List source references with optional type/status filters."""
    statement = select(SourceReference)
    if source_type is not None:
        statement = statement.where(SourceReference.source_type == source_type)
    if drift_status is not None:
        statement = statement.where(SourceReference.drift_status == drift_status)
    statement = statement.order_by(SourceReference.captured_at.desc(), SourceReference.id).limit(
        limit
    )
    return list(session.scalars(statement))


def update_source_reference(
    session: Session,
    reference: SourceReference,
    *,
    actor_id: str,
    source_subsystem: str = "api",
    content: str | bytes | None = None,
    **changes: Any,
) -> SourceReference:
    """Update mutable source-reference fields and record one audit event."""
    before = _reference_summary(reference)
    for field, value in changes.items():
        if value is not None:
            setattr(reference, field, value)
    if content is not None and "content_hash" not in changes:
        reference.content_hash = compute_source_hash_for_reference(
            source_type=reference.source_type,
            stable_locator=reference.stable_locator,
            passage_range=reference.passage_range,
            content=content,
            hash_algorithm=reference.hash_algorithm,
        )
    session.flush()
    record_audit_event(
        session,
        actor_id=actor_id,
        action="update",
        entity_type="SourceReference",
        entity_id=reference.id,
        source_subsystem=source_subsystem,
        before_summary=before,
        after_summary=_reference_summary(reference),
    )
    return reference


def delete_source_reference(
    session: Session,
    reference: SourceReference,
    *,
    actor_id: str,
    source_subsystem: str = "api",
) -> None:
    """Delete a source reference and record the authoring audit event."""
    before = _reference_summary(reference)
    entity_id = reference.id
    session.delete(reference)
    session.flush()
    record_audit_event(
        session,
        actor_id=actor_id,
        action="delete",
        entity_type="SourceReference",
        entity_id=entity_id,
        source_subsystem=source_subsystem,
        before_summary=before,
    )


def compute_source_hash_for_reference(
    *,
    source_type: str,
    stable_locator: str,
    passage_range: str | None,
    content: str | bytes | None,
    hash_algorithm: str,
    base_path: str | Path | None = None,
) -> str:
    """Compute the hash for a reference from content or its locator."""
    if content is not None:
        return compute_source_hash(content, hash_algorithm=hash_algorithm)
    if source_type == "markdown-file":
        return compute_source_hash(
            markdown_path=stable_locator,
            passage_range=passage_range,
            hash_algorithm=hash_algorithm,
            base_path=base_path,
        )
    raise ValueError("content or content_hash is required for non-file source references")


def scan_source_references(
    session: Session,
    *,
    base_path: str | Path | None = None,
    actor_id: str = "system:drift-scan",
) -> DriftScanSummary:
    """Refresh drift status for file-backed source references."""
    scanned = current = stale = missing = skipped = 0
    references = list(session.scalars(select(SourceReference).order_by(SourceReference.id)))
    for reference in references:
        if reference.source_type != "markdown-file":
            skipped += 1
            continue
        scanned += 1
        before = _reference_summary(reference)
        try:
            new_hash = compute_source_hash_for_reference(
                source_type=reference.source_type,
                stable_locator=reference.stable_locator,
                passage_range=reference.passage_range,
                content=None,
                hash_algorithm=reference.hash_algorithm,
                base_path=base_path,
            )
        except FileNotFoundError:
            new_status = "missing"
            missing += 1
        else:
            new_status = "current" if new_hash == reference.content_hash else "stale"
            if new_status == "current":
                current += 1
            else:
                stale += 1
        if reference.drift_status == new_status:
            continue
        reference.drift_status = new_status
        session.flush()
        record_audit_event(
            session,
            actor_id=actor_id,
            action="drift-status",
            entity_type="SourceReference",
            entity_id=reference.id,
            source_subsystem="drift-scan",
            before_summary=before,
            after_summary=_reference_summary(reference),
        )
    return DriftScanSummary(
        scanned=scanned,
        current=current,
        stale=stale,
        missing=missing,
        skipped=skipped,
    )


def _source_payload(
    content: str | bytes | None,
    *,
    markdown_path: str | Path | None,
    passage_range: str | None,
    base_path: str | Path | None,
) -> str | bytes:
    if content is not None:
        return content
    if markdown_path is None:
        raise ValueError("content or markdown_path is required to compute a source hash")
    path = Path(markdown_path)
    if not path.is_absolute() and base_path is not None:
        path = Path(base_path) / path
    text = path.read_text(encoding="utf-8")
    return _select_passage(text, passage_range)


def _select_passage(text: str, passage_range: str | None) -> str:
    if not passage_range:
        return text
    match = _LINE_RANGE_PATTERN.match(passage_range.strip())
    if match is None:
        return text
    start = max(int(match.group("start")), 1)
    end = int(match.group("end") or start)
    if end < start:
        start, end = end, start
    lines = text.splitlines(keepends=True)
    return "".join(lines[start - 1 : end])


def _reference_summary(reference: SourceReference) -> Mapping[str, Any]:
    return {
        "id": reference.id,
        "source_type": reference.source_type,
        "stable_locator": reference.stable_locator,
        "passage_range": reference.passage_range,
        "content_hash": reference.content_hash,
        "hash_algorithm": reference.hash_algorithm,
        "source_visibility": reference.source_visibility,
        "drift_status": reference.drift_status,
        "multi_source_role": reference.multi_source_role,
    }
