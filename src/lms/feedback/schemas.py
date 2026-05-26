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
OwnershipScope = Literal["personal", "institutional"]
RubricStatus = Literal["draft", "published", "archived"]
RubricCriterionStatus = Literal["active", "archived"]


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


class RubricCriterionCreate(BaseModel):
    """Input for creating one rubric criterion."""

    criterion_order: int = Field(ge=1)
    description: str = Field(min_length=1)
    max_points: float = Field(gt=0)
    performance_levels: dict[str, object] = Field(default_factory=dict)
    validity_scope: str | None = Field(default=None, max_length=255)
    status: RubricCriterionStatus = "active"


class RubricCriterionRootCreate(RubricCriterionCreate):
    """Input for creating a criterion through the top-level criterion route."""

    rubric_id: str = Field(min_length=1, max_length=36)


class RubricCriterionUpdate(BaseModel):
    """Mutable rubric criterion fields."""

    criterion_order: int | None = Field(default=None, ge=1)
    description: str | None = Field(default=None, min_length=1)
    max_points: float | None = Field(default=None, gt=0)
    performance_levels: dict[str, object] | None = None
    validity_scope: str | None = Field(default=None, max_length=255)
    status: RubricCriterionStatus | None = None


class RubricCriterionRead(RubricCriterionCreate):
    """Serializable rubric criterion."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    rubric_id: str
    created_at: datetime
    updated_at: datetime


class RubricCreate(BaseModel):
    """Input for creating a rubric and optional nested criteria."""

    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    ownership_scope: OwnershipScope
    prompt_id: str | None = Field(default=None, max_length=36)
    knowledge_node_id: str | None = Field(default=None, max_length=36)
    case_id: str | None = Field(default=None, max_length=36)
    status: RubricStatus = "draft"
    authoring_actor: str = Field(min_length=1, max_length=255)
    reviewing_actor: str | None = Field(default=None, max_length=255)
    criteria: list[RubricCriterionCreate] = Field(default_factory=list)


class RubricUpdate(BaseModel):
    """Mutable rubric fields."""

    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    prompt_id: str | None = Field(default=None, max_length=36)
    knowledge_node_id: str | None = Field(default=None, max_length=36)
    case_id: str | None = Field(default=None, max_length=36)
    status: RubricStatus | None = None
    reviewing_actor: str | None = Field(default=None, max_length=255)


class RubricRead(BaseModel):
    """Serializable rubric with criteria in deterministic order."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    description: str | None
    ownership_scope: str
    prompt_id: str | None
    knowledge_node_id: str | None
    case_id: str | None
    status: str
    authoring_actor: str
    reviewing_actor: str | None
    created_at: datetime
    updated_at: datetime
    criteria: list[RubricCriterionRead]
