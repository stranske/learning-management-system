"""Pydantic schemas for competencies."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from lms.graphs.schemas import KnowledgeType, OwnershipScope

CompetencyStatus = Literal["draft", "active", "deprecated"]
EvidenceRole = Literal["supports", "contradicts", "demonstrates", "prerequisite"]


class CompetencyCreate(BaseModel):
    """Input for creating a competency."""

    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    ownership_scope: OwnershipScope
    target_knowledge_type: KnowledgeType
    validity_scope: str | None = None
    status: CompetencyStatus = "draft"


class CompetencyRead(BaseModel):
    """Serializable competency definition."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    description: str | None
    ownership_scope: str
    target_knowledge_type: str
    validity_scope: str | None
    status: str
    created_at: datetime
    updated_at: datetime


class CompetencyEvidenceCreate(BaseModel):
    """Input for linking evidence to a competency."""

    competency_id: str = Field(min_length=1, max_length=36)
    knowledge_node_id: str = Field(min_length=1, max_length=36)
    evidence_record_id: str = Field(min_length=1, max_length=36)
    contribution_weight: float = Field(default=1.0, ge=0.0, le=1.0)
    evidence_role: EvidenceRole = "supports"
    actor_id: str = Field(default="system:api", min_length=1, max_length=255)


class CompetencyEvidenceRead(BaseModel):
    """Serializable competency evidence link."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    competency_id: str
    knowledge_node_id: str
    evidence_record_id: str
    learner_id: str
    contribution_weight: float
    evidence_role: str
    created_at: datetime
