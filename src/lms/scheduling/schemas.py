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
ScheduleState = Literal["scheduled", "completed", "skipped", "stale"]


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


class ReviewPolicyRead(BaseModel):
    """Serializable scheduler policy record."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    policy_version: str
    reason_code: ReasonCode
    knowledge_type: str | None
    ownership_scope: str | None
    settings: dict[str, Any]
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ReviewScheduleRead(BaseModel):
    """Serializable durable review schedule."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    learner_id: str
    knowledge_node_id: str
    review_policy_id: str | None
    review_queue_item_id: str | None
    reason_code: ReasonCode
    schedule_state: ScheduleState
    due_at: datetime
    policy_version: str
    knowledge_type: str | None
    ownership_scope: str | None
    source_evidence_record_id: str | None
    created_at: datetime
    updated_at: datetime


class SchedulerDecisionRead(BaseModel):
    """Serializable explainable scheduler decision."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    learner_id: str
    knowledge_node_id: str
    review_policy_id: str | None
    review_schedule_id: str | None
    review_queue_item_id: str | None
    source_evidence_record_id: str | None
    reason_code: ReasonCode
    decision_rationale: str
    policy_version: str
    knowledge_type: str | None
    ownership_scope: str | None
    support_level: str | None
    decision_log: dict[str, Any]
    created_at: datetime
