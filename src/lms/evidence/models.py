"""SQLAlchemy models for learner attempts and evidence inputs."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    false,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from lms.auth.models import new_uuid, utc_now
from lms.db.base import Base
from lms.graphs.models import KNOWLEDGE_TYPES

SUPPORT_LEVELS: tuple[str, ...] = ("none", "hint", "reference", "worked-example", "coach")
DEMAND_LEVELS: tuple[str, ...] = ("low", "medium", "high")
EVIDENCE_KINDS: tuple[str, ...] = ("observed", "inferred")


def _sql_values(values: tuple[str, ...]) -> str:
    """Return SQL string literals for a check constraint."""
    return ", ".join(f"'{value}'" for value in values)


class Attempt(Base):
    """A learner response to a prompt with structured feedback metadata."""

    __tablename__ = "attempts"
    __table_args__ = (
        CheckConstraint(
            "confidence_rating IS NULL OR " "(confidence_rating >= 1 AND confidence_rating <= 5)",
            name="confidence_rating_valid",
        ),
        CheckConstraint(
            f"support_level IN ({_sql_values(SUPPORT_LEVELS)})",
            name="support_level_valid",
        ),
        CheckConstraint(
            "elapsed_seconds IS NULL OR elapsed_seconds >= 0",
            name="elapsed_seconds_non_negative",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    learner_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    prompt_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    response_text: Mapped[str] = mapped_column(Text, nullable=False)
    response_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    confidence_rating: Mapped[int | None] = mapped_column(Integer)
    reference_accessed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false(), index=True
    )
    hint_used: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    support_level: Mapped[str] = mapped_column(
        String(32), nullable=False, default="none", server_default="none", index=True
    )
    elapsed_seconds: Mapped[int | None] = mapped_column(Integer)
    feedback: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    llm_session_id: Mapped[str | None] = mapped_column(String(36), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        nullable=False,
        index=True,
    )
    evidence_records: Mapped[list[EvidenceRecord]] = relationship(
        "EvidenceRecord",
        back_populates="attempt",
        cascade="all, delete-orphan",
    )


class EvidenceRecord(Base):
    """Verbose evidence signal preserved for future mastery estimation."""

    __tablename__ = "evidence_records"
    __table_args__ = (
        CheckConstraint(
            f"evidence_kind IN ({_sql_values(EVIDENCE_KINDS)})",
            name="evidence_kind_valid",
        ),
        CheckConstraint(
            f"demand_level IS NULL OR demand_level IN ({_sql_values(DEMAND_LEVELS)})",
            name="demand_level_valid",
        ),
        CheckConstraint(
            f"knowledge_type IS NULL OR knowledge_type IN ({_sql_values(KNOWLEDGE_TYPES)})",
            name="knowledge_type_valid",
        ),
        CheckConstraint(
            "time_since_last_attempt_seconds IS NULL OR time_since_last_attempt_seconds >= 0",
            name="time_since_last_attempt_non_negative",
        ),
        CheckConstraint(
            "response_time_seconds IS NULL OR response_time_seconds >= 0",
            name="response_time_non_negative",
        ),
        CheckConstraint(
            "confidence_rating IS NULL OR (confidence_rating >= 1 AND confidence_rating <= 5)",
            name="confidence_rating_valid",
        ),
        CheckConstraint(
            f"support_level IN ({_sql_values(SUPPORT_LEVELS)})",
            name="support_level_valid",
        ),
        CheckConstraint(
            "raw_score IS NULL OR raw_score >= 0",
            name="raw_score_non_negative",
        ),
        CheckConstraint(
            "normalized_score IS NULL OR (normalized_score >= 0.0 AND normalized_score <= 1.0)",
            name="normalized_score_unit_interval",
        ),
        CheckConstraint(
            "max_score IS NULL OR max_score > 0",
            name="max_score_positive",
        ),
        CheckConstraint(
            "item_difficulty_estimate IS NULL OR "
            "(item_difficulty_estimate >= 0.0 AND item_difficulty_estimate <= 1.0)",
            name="item_difficulty_unit_interval",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    attempt_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("attempts.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    learner_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    knowledge_node_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    prompt_id: Mapped[str | None] = mapped_column(String(36), index=True)
    prompt_version_id: Mapped[str | None] = mapped_column(String(36), index=True)
    evidence_kind: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="observed",
        server_default=text("'observed'"),
        index=True,
    )
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        nullable=False,
        index=True,
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        nullable=False,
        index=True,
    )
    demand_level: Mapped[str | None] = mapped_column(String(32), index=True)
    knowledge_type: Mapped[str | None] = mapped_column(String(32), index=True)
    time_since_last_attempt_seconds: Mapped[int | None] = mapped_column(Integer)
    response_time_seconds: Mapped[int | None] = mapped_column(Integer)
    correctness: Mapped[bool | None] = mapped_column(Boolean)
    confidence_rating: Mapped[int | None] = mapped_column(Integer)
    reference_accessed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false(), index=True
    )
    hint_used: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    support_level: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="none",
        server_default=text("'none'"),
        index=True,
    )
    retrieval_demand: Mapped[str | None] = mapped_column(String(64))
    transfer_distance: Mapped[str | None] = mapped_column(String(64))
    source_match_quality: Mapped[str | None] = mapped_column(String(64))
    scorer_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    raw_score: Mapped[float | None] = mapped_column(Float)
    normalized_score: Mapped[float | None] = mapped_column(Float)
    max_score: Mapped[float | None] = mapped_column(Float)
    partial_credit_dimensions: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    item_difficulty_estimate: Mapped[float | None] = mapped_column(Float)
    attempt_context: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    validity_scope: Mapped[str | None] = mapped_column(Text)
    answer_artifact_ref: Mapped[str | None] = mapped_column(String(1024))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        nullable=False,
    )

    attempt: Mapped[Attempt | None] = relationship("Attempt", back_populates="evidence_records")
