"""Pydantic schemas for the review queue API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ReasonCode = Literal[
    "new-learning",
    "due-review",
    "overdue",
    "remediation",
    "stale",
    "blocked-prerequisite",
]
QueueStatus = Literal["pending", "dispatched", "completed", "skipped"]


class ReviewQueueItemRead(BaseModel):
    """Serializable review queue item."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    learner_id: str
    knowledge_node_id: str
    reason_code: ReasonCode
    reason_explanation: str
    due_at: datetime
    priority: float = Field(ge=0.0, le=1.0)
    status: QueueStatus
    source_attempt_id: str | None
    source_evidence_record_id: str | None
    decision_log: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class ReviewQueueResponse(BaseModel):
    """Review queue response with sustainable-use metadata."""

    learner_id: str
    daily_cap: int = Field(ge=1)
    backlog_total: int = Field(ge=0)
    returned_count: int = Field(ge=0)
    backlog_note: str
    items: list[ReviewQueueItemRead]
