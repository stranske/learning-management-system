"""Pydantic schemas for learner endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from lms.graphs.schemas import KnowledgeNodeRead, KnowledgeType, OwnershipScope

GoalStatus = Literal["active", "paused", "completed", "archived"]


class LearnerCreate(BaseModel):
    """Input for creating a learner profile."""

    user_id: str
    display_name: str = Field(min_length=1, max_length=200)
    timezone: str = Field(default="UTC", min_length=1, max_length=80)
    locale: str = Field(default="en-US", min_length=1, max_length=20)


class LearnerRead(BaseModel):
    """Serializable learner profile."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    display_name: str
    timezone: str
    locale: str
    created_at: datetime
    updated_at: datetime


class LearningGoalCreate(BaseModel):
    """Input for creating a learner-owned learning goal."""

    title: str = Field(min_length=1, max_length=255)
    knowledge_type: KnowledgeType
    target_node_ids: list[str] = Field(min_length=1)
    ownership_scope: OwnershipScope
    status: GoalStatus = "active"


class LearningGoalUpdate(BaseModel):
    """Input for updating a learning goal."""

    title: str | None = Field(default=None, min_length=1, max_length=255)
    knowledge_type: KnowledgeType | None = None
    target_node_ids: list[str] | None = Field(default=None, min_length=1)
    ownership_scope: OwnershipScope | None = None
    status: GoalStatus | None = None


class LearningGoalRead(BaseModel):
    """Serializable learning goal."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    learner_id: str
    title: str
    knowledge_type: str
    status: str
    ownership_scope: str
    target_nodes: list[KnowledgeNodeRead]
    created_at: datetime
    updated_at: datetime


class ReflectionCreate(BaseModel):
    """Input for recording a learner's metacognitive reflection."""

    prompt: str = Field(min_length=1)
    response: str = Field(min_length=1)
    knowledge_node_id: str | None = None


class ReflectionRead(BaseModel):
    """Serializable learner reflection."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    learner_id: str
    knowledge_node_id: str | None
    prompt: str
    response: str
    created_at: datetime


class GoalProgressRead(BaseModel):
    """Goal-relative progress: target nodes covered vs. mastered."""

    learner_id: str
    goal_id: str
    target_count: int
    covered_count: int
    mastered_count: int
    mastery_threshold: float
    progress: float


class KnowledgeProfileItem(BaseModel):
    """One learner-state summary row for a knowledge node."""

    learner_id: str
    ownership_scope: OwnershipScope
    knowledge_node_id: str
    knowledge_node_title: str
    knowledge_type: KnowledgeType
    current_estimate: float
    confidence: float
    evidence_count: int
    last_evidence_id: str
    support_dependence_markers: list[str]
    has_transfer_evidence: bool
    next_evidence_needed: str
    generated_at: datetime


class KnowledgeProfileRead(BaseModel):
    """Computed learner knowledge profile scoped to one graph ownership domain."""

    learner_id: str
    ownership_scope: OwnershipScope
    items: list[KnowledgeProfileItem]
