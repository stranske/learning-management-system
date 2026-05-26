"""Pydantic schemas for capability targets."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

PersonalOwnershipScope = Literal["personal"]
CapabilityTargetStatus = Literal["active", "archived"]


class CapabilityTargetCreate(BaseModel):
    """Input for creating a personal capability target."""

    learner_id: str = Field(min_length=1, max_length=36)
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    ownership_scope: PersonalOwnershipScope = "personal"
    learning_goal_id: str | None = Field(default=None, min_length=1, max_length=36)
    target_node_ids: list[str] = Field(default_factory=list)
    target_competency_ids: list[str] = Field(default_factory=list)
    required_evidence_types: list[str] = Field(default_factory=list)
    confidence_threshold: float = Field(default=0.8, ge=0.0, le=1.0)
    status: CapabilityTargetStatus = "active"


class CapabilityTargetUpdate(BaseModel):
    """Input for updating a personal capability target."""

    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    learning_goal_id: str | None = Field(default=None, min_length=1, max_length=36)
    target_node_ids: list[str] | None = None
    target_competency_ids: list[str] | None = None
    required_evidence_types: list[str] | None = None
    confidence_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    status: CapabilityTargetStatus | None = None


class CapabilityTargetRead(BaseModel):
    """Serializable capability target."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    learner_id: str
    title: str
    description: str | None
    ownership_scope: str
    learning_goal_id: str | None
    required_evidence_types: list[str]
    confidence_threshold: float
    status: str
    target_node_ids: list[str]
    target_competency_ids: list[str]
    created_at: datetime
    updated_at: datetime
