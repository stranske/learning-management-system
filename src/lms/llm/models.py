"""SQLAlchemy models for LLM sessions, traces, and accounting."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from lms.auth.models import new_uuid, utc_now
from lms.db.base import Base

TRACE_CLASSES: tuple[str, ...] = ("evidence-grade", "formative", "ephemeral")
LLM_MODES: tuple[str, ...] = ("study-coach", "practice", "transfer", "authoring-assist")
COACHING_INTENSITIES: tuple[str, ...] = ("full", "light", "quiet")
TRACE_CONTROL_STATES: tuple[str, ...] = ("default", "kept", "forgotten")
LLM_FEEDBACK_EVENT_TYPES: tuple[str, ...] = (
    "learning-policy-nudge",
    "feedback-outcome",
    "source-citation-check",
    "manual-review",
)


def _sql_values(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


class LLMSession(Base):
    """One call (or replay) through the LLM client wrapper.

    Each row records the routing decision, trace class, redaction outcome, and
    accounting needed to audit privacy posture and per-mode cost.
    """

    __tablename__ = "llm_sessions"
    __table_args__ = (
        CheckConstraint(
            f"trace_class IN ({_sql_values(TRACE_CLASSES)})",
            name="trace_class_valid",
        ),
        CheckConstraint(
            f"mode IN ({_sql_values(LLM_MODES)})",
            name="mode_valid",
        ),
        CheckConstraint(
            f"coaching_intensity IN ({_sql_values(COACHING_INTENSITIES)})",
            name="coaching_intensity_valid",
        ),
        CheckConstraint(
            f"trace_control_state IN ({_sql_values(TRACE_CONTROL_STATES)})",
            name="trace_control_state_valid",
        ),
        CheckConstraint(
            "input_tokens >= 0 AND output_tokens >= 0 AND cost_micro_usd >= 0",
            name="accounting_non_negative",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    mode: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    trace_class: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    prompt_template_version: Mapped[str | None] = mapped_column(String(120))
    learner_id: Mapped[str | None] = mapped_column(String(36), index=True)
    coaching_intensity: Mapped[str] = mapped_column(
        String(32), nullable=False, default="full", server_default="full", index=True
    )
    trace_control_state: Mapped[str] = mapped_column(
        String(32), nullable=False, default="default", server_default="default", index=True
    )
    parent_session_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("llm_sessions.id", ondelete="SET NULL"),
    )
    input_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    output_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    cost_micro_usd: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    redaction_applied: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    redacted_span_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    external_export_allowed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    response_summary: Mapped[str | None] = mapped_column(Text)
    transcript_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_replay: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        nullable=False,
    )
    feedback_events: Mapped[list[LLMFeedbackEvent]] = relationship(
        "LLMFeedbackEvent",
        back_populates="llm_session",
        cascade="all, delete-orphan",
    )


class LearningInteractionSkill(Base):
    """Named learning-policy skill that can be audited across LLM turns."""

    __tablename__ = "learning_interaction_skills"
    __table_args__ = (
        CheckConstraint(
            f"mode IN ({_sql_values(LLM_MODES)})",
            name="learning_interaction_skill_mode_valid",
        ),
        UniqueConstraint("name", "policy_version", name="learning_interaction_skill_name_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    mode: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    policy_version: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    allowed_trace_classes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    source_citation_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true(), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        nullable=False,
        index=True,
    )
    feedback_events: Mapped[list[LLMFeedbackEvent]] = relationship(
        "LLMFeedbackEvent",
        back_populates="skill",
    )


class LLMFeedbackEvent(Base):
    """Per-turn feedback fact emitted by an LLM session."""

    __tablename__ = "llm_feedback_events"
    __table_args__ = (
        CheckConstraint(
            f"event_type IN ({_sql_values(LLM_FEEDBACK_EVENT_TYPES)})",
            name="llm_feedback_event_type_valid",
        ),
        CheckConstraint(
            f"trace_class IN ({_sql_values(TRACE_CLASSES)})",
            name="llm_feedback_event_trace_class_valid",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    llm_session_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("llm_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    learner_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    skill_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("learning_interaction_skills.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    feedback_record_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("feedback_records.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    evidence_record_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("evidence_records.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    trace_class: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    source_reference_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    unverified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false(), index=True
    )
    cost_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    event_summary: Mapped[str | None] = mapped_column(Text)
    event_body: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        nullable=False,
        index=True,
    )

    llm_session: Mapped[LLMSession] = relationship(
        "LLMSession",
        back_populates="feedback_events",
    )
    skill: Mapped[LearningInteractionSkill | None] = relationship(
        "LearningInteractionSkill",
        back_populates="feedback_events",
    )
