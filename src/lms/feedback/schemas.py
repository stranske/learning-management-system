"""Pydantic schemas for durable feedback records and actions."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

FeedbackLevel = Literal["affirmation", "coaching", "remediation", "review"]
FeedbackActionType = Literal[
    "retry",
    "parallel-prompt",
    "prerequisite-remediation",
    "model-comparison",
    "revision",
    "coach-review",
    "author-review",
]
FeedbackActionStatus = Literal["open", "in-progress", "completed", "dismissed"]


class FeedbackRecordCreate(BaseModel):
    """Input for creating a durable feedback record."""

    learner_id: str = Field(min_length=1, max_length=36)
    attempt_id: str | None = Field(default=None, max_length=36)
    prompt_id: str | None = Field(default=None, max_length=36)
    evidence_record_id: str | None = Field(default=None, max_length=36)
    feedback_level: FeedbackLevel = "coaching"
    goal: str = Field(min_length=1)
    observed_evidence: str = Field(min_length=1)
    diagnosis: str | None = None
    gap: str | None = None
    source_feedback: dict[str, object] | None = None
    next_action_ids: list[str] = Field(default_factory=list)


class FeedbackRecordRead(FeedbackRecordCreate):
    """Serializable durable feedback record."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    source_feedback: dict[str, object]
    created_at: datetime


class FeedbackActionCreate(BaseModel):
    """Input for creating an action linked to feedback."""

    learner_id: str = Field(min_length=1, max_length=36)
    feedback_record_id: str | None = Field(default=None, max_length=36)
    attempt_id: str | None = Field(default=None, max_length=36)
    prompt_id: str | None = Field(default=None, max_length=36)
    action_type: FeedbackActionType
    status: FeedbackActionStatus = "open"
    title: str = Field(min_length=1)
    instructions: str | None = None
    due_at: datetime | None = None
    action_metadata: dict[str, object] | None = None


class FeedbackActionRead(FeedbackActionCreate):
    """Serializable feedback action."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    updated_at: datetime
