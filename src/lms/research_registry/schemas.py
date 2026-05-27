"""Pydantic schemas for the build-time research registry."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class EvidenceLevel(StrEnum):
    """Evidence strength values from the research domain model."""

    ESTABLISHED = "established"
    PROMISING = "promising"
    MIXED = "mixed"
    UNSUPPORTED = "unsupported"
    DEPRECATED = "deprecated"
    UNKNOWN = "unknown"


class ClaimStatus(StrEnum):
    """Lifecycle state for a learning claim."""

    ESTABLISHED = "established"
    PROMISING = "promising"
    MIXED = "mixed"
    UNSUPPORTED = "unsupported"
    DEPRECATED = "deprecated"
    NEEDS_REVIEW = "needs-review"


class SourceType(StrEnum):
    """Allowed evidence source categories."""

    BOOK = "book"
    JOURNAL_ARTICLE = "journal-article"
    BOOK_CHAPTER = "book-chapter"
    REVIEW = "review"
    META_ANALYSIS = "meta-analysis"
    INTERNAL_EXPERIMENT = "internal-experiment"
    PERSONAL_HIGHLIGHT = "personal-highlight"
    POPULAR_HIGHLIGHT = "popular-highlight"
    PROJECT_DECISION = "project-decision"


class ReviewCadence(StrEnum):
    """Allowed claim review cadences."""

    QUARTERLY = "quarterly"
    SEMIANNUAL = "semiannual"
    ANNUAL = "annual"
    ON_NEW_EVIDENCE = "on-new-evidence"


class Confidence(StrEnum):
    """Confidence values for learning principles."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Audience(StrEnum):
    """Audience values from the design model."""

    PERSONAL = "personal"
    NEW_ANALYST = "new-analyst"
    COMPANY_WIDE = "company-wide"


class ClaimType(StrEnum):
    """Operational claim categories."""

    DESCRIPTIVE = "descriptive"
    CAUSAL = "causal"
    DESIGN_RULE = "design-rule"
    MEASUREMENT_RULE = "measurement-rule"
    RISK_WARNING = "risk-warning"


class ResearchDecision(StrEnum):
    """Decision outcomes for research-hygiene records.

    Mirrors the ``decision`` enum on the Experiment entity in the research
    domain model so scans and reviews share one decision vocabulary.
    """

    ADOPT = "adopt"
    ITERATE = "iterate"
    REJECT = "reject"
    NEEDS_MORE_DATA = "needs-more-data"
    MONITOR = "monitor"


class EvidenceReviewStatus(StrEnum):
    """Lifecycle state for an evidence review."""

    PENDING = "pending"
    IN_REVIEW = "in-review"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    NEEDS_FOLLOWUP = "needs-followup"


class RegistryModel(BaseModel):
    """Base model accepting the camel-case field names used in YAML."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class LearningPrinciple(RegistryModel):
    """A durable learning-science principle used by product design."""

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    mechanism: str = Field(min_length=1)
    source_ids: list[str] = Field(default_factory=list, alias="sourceIds")
    evidence_level: EvidenceLevel = Field(alias="evidenceLevel")
    confidence: Confidence
    design_implications: list[str] = Field(alias="designImplications", min_length=1)
    anti_patterns: list[str] = Field(default_factory=list, alias="antiPatterns")
    audiences: list[Audience] = Field(min_length=1)
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class EvidenceSource(RegistryModel):
    """A bibliographic or internal source used by registry records."""

    id: str = Field(min_length=1)
    source_type: SourceType = Field(alias="sourceType")
    citation: str = Field(min_length=1)
    url: HttpUrl | None = None
    source_date: date | None = Field(default=None, alias="sourceDate")
    reliability_notes: str = Field(min_length=1, alias="reliabilityNotes")
    copyright_notes: str = Field(min_length=1, alias="copyrightNotes")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class LearningClaim(RegistryModel):
    """A specific claim derived from one or more principles or sources."""

    id: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    principle_ids: list[str] = Field(alias="principleIds", min_length=1)
    source_ids: list[str] = Field(default_factory=list, alias="sourceIds")
    claim_status: ClaimStatus = Field(alias="claimStatus")
    claim_type: ClaimType = Field(alias="claimType")
    scope: str = Field(min_length=1)
    review_cadence: ReviewCadence = Field(alias="reviewCadence")
    last_reviewed_at: datetime = Field(alias="lastReviewedAt")


class ResearchScan(RegistryModel):
    """A periodic research-hygiene scan of a topic's evidence and claims."""

    id: str = Field(min_length=1)
    topic: str = Field(min_length=1)
    scan_date: date = Field(alias="scanDate")
    source_ids: list[str] = Field(default_factory=list, alias="sourceIds")
    claim_ids: list[str] = Field(default_factory=list, alias="claimIds")
    summary: str = Field(min_length=1)
    decision: ResearchDecision
    next_review_at: datetime = Field(alias="nextReviewAt")
    reviewer: str = Field(min_length=1)


class EvidenceReview(RegistryModel):
    """A structured review of one evidence source against the claims it informs."""

    id: str = Field(min_length=1)
    evidence_source_id: str = Field(min_length=1, alias="evidenceSourceId")
    claim_ids: list[str] = Field(default_factory=list, alias="claimIds")
    review_status: EvidenceReviewStatus = Field(alias="reviewStatus")
    reliability_notes: str = Field(min_length=1, alias="reliabilityNotes")
    limitations: str = Field(min_length=1)
    decision: ResearchDecision
    reviewed_at: datetime = Field(alias="reviewedAt")
