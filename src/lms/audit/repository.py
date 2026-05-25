"""Repository helpers for recording and querying authoring audit events.

Audited entities (per Milestone 2 plan): ``KnowledgeNode``, ``KnowledgeEdge``,
``Prompt``, ``SourceReference``, and the future ``Rubric`` record. New CRUD or
importer code paths added in later issues MUST call :func:`record_audit_event`
when they create or mutate any of those entities.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from lms.audit.models import AuditLog

AUDITED_ENTITY_TYPES: frozenset[str] = frozenset(
    {
        "KnowledgeNode",
        "KnowledgeEdge",
        "Prompt",
        "SourceReference",
        "Rubric",
    }
)


def record_audit_event(
    session: Session,
    *,
    actor_id: str,
    action: str,
    entity_type: str,
    entity_id: str,
    source_subsystem: str,
    before_summary: Mapping[str, Any] | None = None,
    after_summary: Mapping[str, Any] | None = None,
    occurred_at: datetime | None = None,
) -> AuditLog:
    """Persist a single authoring audit event and return the stored row.

    The caller is responsible for owning the transaction. The helper flushes so
    the returned row carries its server-assigned primary key but does not
    commit.
    """
    event = AuditLog(
        actor_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        before_summary=dict(before_summary) if before_summary is not None else None,
        after_summary=dict(after_summary) if after_summary is not None else None,
        source_subsystem=source_subsystem,
    )
    if occurred_at is not None:
        event.occurred_at = occurred_at
    session.add(event)
    session.flush()
    return event


def list_audit_events(
    session: Session,
    *,
    entity_type: str | None = None,
    actor_id: str | None = None,
    limit: int = 100,
) -> Sequence[AuditLog]:
    """Return audit events optionally filtered by entity type and actor id."""
    statement = select(AuditLog)
    if entity_type is not None:
        statement = statement.where(AuditLog.entity_type == entity_type)
    if actor_id is not None:
        statement = statement.where(AuditLog.actor_id == actor_id)
    statement = statement.order_by(AuditLog.occurred_at.desc(), AuditLog.id.desc()).limit(limit)
    return list(session.execute(statement).scalars())
