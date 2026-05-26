"""Pydantic schemas for transfer case shells."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

OwnershipScope = Literal["personal", "institutional"]
CaseStatus = Literal["draft", "published", "archived"]
DecisionPointType = Literal["single-choice", "free-response", "evidence-selection"]


class CaseStepCreate(BaseModel):
    step_order: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=255)
    prompt: str = Field(min_length=1)
    expected_work_product: str | None = None


class EvidencePacketCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    summary: str | None = None
    source_reference_id: str | None = Field(default=None, min_length=1, max_length=36)
    packet_metadata: dict[str, Any] = Field(default_factory=dict)


class DecisionPointCreate(BaseModel):
    case_step_id: str = Field(min_length=1, max_length=36)
    title: str = Field(min_length=1, max_length=255)
    prompt: str = Field(min_length=1)
    decision_type: DecisionPointType
    evidence_packet_id: str | None = Field(default=None, min_length=1, max_length=36)
    options: list[dict[str, Any]] = Field(default_factory=list)


class CaseCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    ownership_scope: OwnershipScope
    rubric_id: str | None = Field(default=None, min_length=1, max_length=36)
    knowledge_node_id: str | None = Field(default=None, min_length=1, max_length=36)
    status: CaseStatus = "draft"
    steps: list[CaseStepCreate] = Field(default_factory=list)
    evidence_packets: list[EvidencePacketCreate] = Field(default_factory=list)


class DecisionPointRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    case_step_id: str
    evidence_packet_id: str | None
    title: str
    prompt: str
    decision_type: str
    options: list[dict[str, Any]]
    created_at: datetime


class CaseStepRead(BaseModel):
    id: str
    case_id: str
    step_order: int
    title: str
    prompt: str
    expected_work_product: str | None
    decision_points: list[DecisionPointRead] = Field(default_factory=list)
    created_at: datetime


class EvidencePacketRead(BaseModel):
    id: str
    case_id: str
    title: str
    summary: str | None
    source_reference_id: str | None
    packet_metadata: dict[str, Any]
    created_at: datetime


class CaseRead(BaseModel):
    id: str
    title: str
    description: str | None
    ownership_scope: str
    rubric_id: str | None
    knowledge_node_id: str | None
    status: str
    steps: list[CaseStepRead]
    evidence_packets: list[EvidencePacketRead]
    created_at: datetime
    updated_at: datetime

