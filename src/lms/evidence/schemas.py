"""Pydantic schemas for attempt submission and reads."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SupportLevel = Literal["none", "hint", "reference", "worked-example", "coach"]
EvidenceKind = Literal["observed", "inferred"]
ValidityScope = Literal["attempt", "session", "node", "course"]


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
    scoring: "EvidenceRecordCreate | None" = None

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


class EvidenceRecordCreate(BaseModel):
    """Input for a verbose evidence record."""

    learner_id: str = Field(min_length=1, max_length=36)
    knowledge_node_id: str = Field(min_length=1, max_length=36)
    prompt_id: str = Field(min_length=1, max_length=36)
    prompt_version_id: str | None = Field(default=None, max_length=36)
    attempt_id: str | None = Field(default=None, max_length=36)
    evidence_kind: EvidenceKind = "observed"
    demand_level: str = Field(min_length=1, max_length=32)
    knowledge_type: str = Field(min_length=1, max_length=32)
    time_since_last_attempt_seconds: int | None = Field(default=None, ge=0)
    response_time_seconds: int | None = Field(default=None, ge=0)
    correctness: bool | None = None
    confidence_rating: int | None = Field(default=None, ge=1, le=5)
    hint_used: bool = False
    reference_accessed: bool = False
    support_level: SupportLevel = "none"
    retrieval_demand: str | None = Field(default=None, max_length=120)
    transfer_distance: str | None = Field(default=None, max_length=120)
    source_match_quality: str | None = Field(default=None, max_length=120)
    scorer_id: str | None = Field(default=None, max_length=255)
    scorer_version: str | None = Field(default=None, max_length=120)
    raw_score: float | None = None
    normalized_score: float | None = Field(default=None, ge=0.0, le=1.0)
    max_score: float | None = None
    partial_credit_dimensions: dict[str, float] | None = None
    item_difficulty_estimate: float | None = None
    attempt_context: dict[str, object] | None = None
    validity_scope: ValidityScope = "attempt"
    answer_artifact_ref: str | None = Field(default=None, max_length=1024)

    @model_validator(mode="after")
    def raw_score_does_not_exceed_max(self) -> "EvidenceRecordCreate":
        """Validate partial-credit score bounds."""
        if (
            self.raw_score is not None
            and self.max_score is not None
            and self.raw_score > self.max_score
        ):
            raise ValueError("raw_score cannot exceed max_score")
        return self


class EvidenceRecordRead(EvidenceRecordCreate):
    """Serializable evidence record."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    recorded_at: datetime
