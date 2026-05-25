"""Pydantic schemas for the audit-events HTTP surface."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class AuditEventRead(BaseModel):
    """Read-side projection of :class:`lms.audit.models.AuditLog`."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    actor_id: str
    action: str
    entity_type: str
    entity_id: str
    before_summary: dict[str, Any] | None
    after_summary: dict[str, Any] | None
    source_subsystem: str
    occurred_at: datetime
