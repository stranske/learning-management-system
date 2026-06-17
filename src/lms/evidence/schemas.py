"""Pydantic schemas for attempt submission and evidence reads."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SupportLevel = Literal["none", "hint", "reference", "worked-example", "coach"]
DemandLevel = Literal["low", "medium", "high"]
EvidenceKind = Literal["observed", "inferred"]
KnowledgeType = Literal[
    "factual",
    "conceptual",
    "procedural",
    "judgment",
    "metacognitive",
    "social",
    "compliance",
]


class StructuredFeedback(BaseModel):
    """Structured feedback captured directly on an attempt."""

    goal: str = Field(min_length=1)
    observed_evidence: str = Field(min_length=1)
    gap: str | None = None
    next_action: str = Field(min_length=1)


class AttemptCreate(BaseModel):
    """Input for recording a learner attempt."""

    learner_id: str = Field(min_length=1, max_length=36)
    prompt_id: str = Field(min_length=1, max_length=36)
    response_text: str = Field(min_length=1)
    response_metadata: dict[str, object] | None = None
    confidence_rating: int | None = Field(default=None, ge=1, le=5)
    reference_accessed: bool = False
    hint_used: bool = False
    support_level: SupportLevel = "none"
    elapsed_seconds: int | None = Field(default=None, ge=0)
    feedback: StructuredFeedback
    llm_session_id: str | None = Field(default=None, max_length=36)
    evidence: AttemptEvidenceCreate | None = None

    @model_validator(mode="after")
    def reference_support_matches_access(self) -> AttemptCreate:
        """Keep reference-use fields coherent for downstream evidence adapters."""
        if self.support_level == "reference" and not self.reference_accessed:
            self.reference_accessed = True
        if self.hint_used and self.support_level == "none":
            self.support_level = "hint"
        return self


class AttemptRead(BaseModel):
    """Serializable attempt payload."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    learner_id: str
    prompt_id: str
    response_text: str
    response_metadata: dict[str, object] | None
    confidence_rating: int | None
    reference_accessed: bool
    hint_used: bool
    support_level: SupportLevel
    elapsed_seconds: int | None
    feedback: StructuredFeedback
    llm_session_id: str | None
    created_at: datetime


class AttemptEvidenceCreate(BaseModel):
    """Evidence payload created atomically with an attempt when scoring exists."""

    knowledge_node_id: str = Field(min_length=1, max_length=36)
    prompt_version_id: str | None = Field(default=None, max_length=36)
    timestamp: datetime | None = None
    evidence_kind: EvidenceKind = "observed"
    demand_level: DemandLevel | None = None
    knowledge_type: KnowledgeType | None = None
    time_since_last_attempt_seconds: int | None = Field(default=None, ge=0)
    response_time_seconds: int | None = Field(default=None, ge=0)
    correctness: bool | None = None
    retrieval_demand: str | None = Field(default=None, max_length=64)
    transfer_distance: str | None = Field(default=None, max_length=64)
    source_match_quality: str | None = Field(default=None, max_length=64)
    scorer_type: str | None = Field(default=None, max_length=64)
    scorer_id: str | None = Field(default=None, max_length=255)
    scorer_version: str | None = Field(default=None, max_length=120)
    scoring_method: str | None = Field(default=None, max_length=32)
    scorer_metadata: dict[str, object] | None = None
    raw_score: float | None = Field(default=None, ge=0)
    normalized_score: float | None = Field(default=None, ge=0, le=1)
    max_score: float | None = Field(default=None, gt=0)
    partial_credit_dimensions: dict[str, object] | None = None
    item_difficulty_estimate: float | None = Field(default=None, ge=0, le=1)
    attempt_context: dict[str, object] | None = None
    validity_scope: str | None = None
    answer_artifact_ref: str | None = Field(default=None, max_length=1024)


class EvidenceRecordCreate(BaseModel):
    """Input for creating standalone observed or inferred evidence."""

    learner_id: str = Field(min_length=1, max_length=36)
    knowledge_node_id: str = Field(min_length=1, max_length=36)
    attempt_id: str | None = Field(default=None, max_length=36)
    prompt_id: str | None = Field(default=None, max_length=36)
    prompt_version_id: str | None = Field(default=None, max_length=36)
    timestamp: datetime | None = None
    evidence_kind: EvidenceKind = "observed"
    demand_level: DemandLevel | None = None
    knowledge_type: KnowledgeType | None = None
    time_since_last_attempt_seconds: int | None = Field(default=None, ge=0)
    response_time_seconds: int | None = Field(default=None, ge=0)
    correctness: bool | None = None
    confidence_rating: int | None = Field(default=None, ge=1, le=5)
    reference_accessed: bool = False
    hint_used: bool = False
    support_level: SupportLevel = "none"
    retrieval_demand: str | None = Field(default=None, max_length=64)
    transfer_distance: str | None = Field(default=None, max_length=64)
    source_match_quality: str | None = Field(default=None, max_length=64)
    scorer_type: str | None = Field(default=None, max_length=64)
    scorer_id: str | None = Field(default=None, max_length=255)
    scorer_version: str | None = Field(default=None, max_length=120)
    scoring_method: str | None = Field(default=None, max_length=32)
    scorer_metadata: dict[str, object] | None = None
    raw_score: float | None = Field(default=None, ge=0)
    normalized_score: float | None = Field(default=None, ge=0, le=1)
    max_score: float | None = Field(default=None, gt=0)
    partial_credit_dimensions: dict[str, object] | None = None
    item_difficulty_estimate: float | None = Field(default=None, ge=0, le=1)
    attempt_context: dict[str, object] | None = None
    validity_scope: str | None = None
    answer_artifact_ref: str | None = Field(default=None, max_length=1024)


class EvidenceRecordRead(EvidenceRecordCreate):
    """Serializable verbose evidence record."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    timestamp: datetime
    observed_at: datetime
    created_at: datetime
