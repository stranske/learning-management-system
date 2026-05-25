"""HTTP read surface for the LMS audit log."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from lms.audit.repository import list_audit_events
from lms.audit.schemas import AuditEventRead
from lms.db.session import get_session

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/events", response_model=list[AuditEventRead])
def read_audit_events(
    session: Annotated[Session, Depends(get_session)],
    entity_type: Annotated[str | None, Query(description="Filter by entity type.")] = None,
    actor_id: Annotated[str | None, Query(description="Filter by actor id.")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[AuditEventRead]:
    """Return audit events filtered by entity type and/or actor id."""
    events = list_audit_events(
        session,
        entity_type=entity_type,
        actor_id=actor_id,
        limit=limit,
    )
    return [AuditEventRead.model_validate(event) for event in events]
