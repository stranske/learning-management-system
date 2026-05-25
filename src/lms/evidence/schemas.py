"""Pydantic schemas for attempt submission and reads."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SupportLevel = Literal["none", "hint", "reference", "worked-example", "coach"]


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
