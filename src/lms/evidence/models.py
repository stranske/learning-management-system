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
    Integer,
    String,
    Text,
    false,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from lms.auth.models import new_uuid, utc_now
from lms.db.base import Base

SUPPORT_LEVELS: tuple[str, ...] = ("none", "hint", "reference", "worked-example", "coach")
EVIDENCE_KINDS: tuple[str, ...] = ("observed", "inferred")
VALIDITY_SCOPES: tuple[str, ...] = ("attempt", "session", "node", "course")


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


class EvidenceRecord(Base):
    """Verbose evidence signal preserved for mastery estimation."""

    __tablename__ = "evidence_records"
    __table_args__ = (
        CheckConstraint(
            f"evidence_kind IN ({_sql_values(EVIDENCE_KINDS)})",
            name="evidence_kind_valid",
        ),
        CheckConstraint(
            f"support_level IN ({_sql_values(SUPPORT_LEVELS)})",
            name="support_level_valid",
        ),
        CheckConstraint(
            f"validity_scope IN ({_sql_values(VALIDITY_SCOPES)})",
            name="validity_scope_valid",
        ),
        CheckConstraint(
            "confidence_rating IS NULL OR " "(confidence_rating >= 1 AND confidence_rating <= 5)",
            name="confidence_rating_valid",
        ),
        CheckConstraint(
            "raw_score IS NULL OR max_score IS NULL OR raw_score <= max_score",
            name="raw_score_not_above_max",
        ),
        CheckConstraint(
            "normalized_score IS NULL OR " "(normalized_score >= 0.0 AND normalized_score <= 1.0)",
            name="normalized_score_unit_interval",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    learner_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    knowledge_node_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    prompt_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    prompt_version_id: Mapped[str | None] = mapped_column(String(36), index=True)
    attempt_id: Mapped[str | None] = mapped_column(String(36), index=True)
    evidence_kind: Mapped[str] = mapped_column(
        String(32), nullable=False, default="observed", server_default="observed", index=True
    )
    demand_level: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    knowledge_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    time_since_last_attempt_seconds: Mapped[int | None] = mapped_column(Integer)
    response_time_seconds: Mapped[int | None] = mapped_column(Integer)
    correctness: Mapped[bool | None] = mapped_column(Boolean)
    confidence_rating: Mapped[int | None] = mapped_column(Integer)
    hint_used: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    reference_accessed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    support_level: Mapped[str] = mapped_column(
        String(32), nullable=False, default="none", server_default="none", index=True
    )
    retrieval_demand: Mapped[str | None] = mapped_column(String(120))
    transfer_distance: Mapped[str | None] = mapped_column(String(120))
    source_match_quality: Mapped[str | None] = mapped_column(String(120))
    scorer_id: Mapped[str | None] = mapped_column(String(255))
    scorer_version: Mapped[str | None] = mapped_column(String(120))
    raw_score: Mapped[float | None] = mapped_column(Float)
    normalized_score: Mapped[float | None] = mapped_column(Float)
    max_score: Mapped[float | None] = mapped_column(Float)
    partial_credit_dimensions: Mapped[dict[str, float] | None] = mapped_column(JSON)
    item_difficulty_estimate: Mapped[float | None] = mapped_column(Float)
    attempt_context: Mapped[dict[str, object] | None] = mapped_column(JSON)
    validity_scope: Mapped[str] = mapped_column(
        String(32), nullable=False, default="attempt", server_default="attempt", index=True
    )
    answer_artifact_ref: Mapped[str | None] = mapped_column(String(1024))
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        nullable=False,
        index=True,
    )
