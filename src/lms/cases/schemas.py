"""Pydantic schemas for transfer case shells."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

OwnershipScope = Literal["personal", "institutional"]
CaseStatus = Literal["draft", "published", "archived"]
DecisionPointType = Literal["single-choice", "free-response", "evidence-selection"]
WorkProductSubmissionType = Literal[
    "memo", "rationale", "classification", "analysis", "artifact", "other"
]
WorkProductStatus = Literal[
    "draft", "submitted", "scored", "revision-requested", "accepted", "withdrawn"
]


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


class WorkProductCreate(BaseModel):
    learner_id: str = Field(min_length=1, max_length=36)
    submission_type: WorkProductSubmissionType
    case_step_id: str | None = Field(default=None, min_length=1, max_length=36)
    rubric_id: str | None = Field(default=None, min_length=1, max_length=36)
    prompt_id: str | None = Field(default=None, min_length=1, max_length=36)
    body: str | None = Field(default=None, min_length=1)
    artifact_ref: str | None = Field(default=None, min_length=1, max_length=1024)

    @model_validator(mode="after")
    def _require_body_or_artifact(self) -> WorkProductCreate:
        if self.body is None and self.artifact_ref is None:
            raise ValueError("work product must include a body or an artifact_ref")
        return self


class WorkProductScoreCreate(BaseModel):
    scorer_type: str = Field(min_length=1, max_length=80)
    criterion_scores: list[dict[str, Any]] = Field(default_factory=list)
    raw_score: float = Field(ge=0.0)
    max_score: float = Field(gt=0.0)
    normalized_score: float | None = Field(default=None, ge=0.0, le=1.0)
    scorer_id: str | None = Field(default=None, min_length=1, max_length=255)
    scorer_version: str | None = Field(default=None, min_length=1, max_length=120)
    knowledge_node_id: str | None = Field(default=None, min_length=1, max_length=36)
    transfer_distance: str = Field(default="case-transfer", min_length=1, max_length=64)
    validity_scope: str | None = None
    score_metadata: dict[str, Any] = Field(default_factory=dict)


class WorkProductScoreRead(BaseModel):
    work_product_id: str
    rubric_score_id: str
    evidence_record_id: str | None
    normalized_score: float
    status: str


class WorkProductRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    case_id: str
    case_step_id: str | None
    learner_id: str
    rubric_id: str | None
    prompt_id: str | None
    submission_type: str
    body: str | None
    artifact_ref: str | None
    status: str
    rubric_score_id: str | None
    revision_request_id: str | None
    submitted_at: datetime
    created_at: datetime
    updated_at: datetime
