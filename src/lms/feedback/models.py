"""SQLAlchemy models for durable learner feedback records and actions."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from lms.auth.models import new_uuid, utc_now
from lms.db.base import Base
from lms.evidence.models import _sql_values

FEEDBACK_LEVELS: tuple[str, ...] = ("affirmation", "coaching", "remediation", "review")
FEEDBACK_ACTION_TYPES: tuple[str, ...] = (
    "retry",
    "parallel-prompt",
    "prerequisite-remediation",
    "model-comparison",
    "revision",
    "coach-review",
    "author-review",
)
FEEDBACK_ACTION_STATUSES: tuple[str, ...] = ("open", "in-progress", "completed", "dismissed")


class FeedbackRecord(Base):
    """Durable feedback diagnosis promoted from attempt-level feedback."""

    __tablename__ = "feedback_records"
    __table_args__ = (
        CheckConstraint(
            f"feedback_level IN ({_sql_values(FEEDBACK_LEVELS)})",
            name="feedback_record_level_valid",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    learner_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    attempt_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("attempts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    prompt_id: Mapped[str | None] = mapped_column(String(36), index=True)
    evidence_record_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("evidence_records.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    feedback_level: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="coaching",
        server_default=text("'coaching'"),
        index=True,
    )
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    observed_evidence: Mapped[str] = mapped_column(Text, nullable=False)
    diagnosis: Mapped[str | None] = mapped_column(Text)
    gap: Mapped[str | None] = mapped_column(Text)
    source_feedback: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    next_action_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        nullable=False,
        index=True,
    )

    actions: Mapped[list[FeedbackAction]] = relationship(
        "FeedbackAction",
        back_populates="feedback_record",
        cascade="all, delete-orphan",
    )


class FeedbackAction(Base):
    """Actionable learner or author follow-up derived from a feedback record."""

    __tablename__ = "feedback_actions"
    __table_args__ = (
        CheckConstraint(
            f"action_type IN ({_sql_values(FEEDBACK_ACTION_TYPES)})",
            name="feedback_action_type_valid",
        ),
        CheckConstraint(
            f"status IN ({_sql_values(FEEDBACK_ACTION_STATUSES)})",
            name="feedback_action_status_valid",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    feedback_record_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("feedback_records.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    learner_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    attempt_id: Mapped[str | None] = mapped_column(String(36), index=True)
    prompt_id: Mapped[str | None] = mapped_column(String(36), index=True)
    action_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="open",
        server_default=text("'open'"),
        index=True,
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    instructions: Mapped[str | None] = mapped_column(Text)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    action_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        nullable=False,
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        server_default=func.now(),
        nullable=False,
    )

    feedback_record: Mapped[FeedbackRecord | None] = relationship(
        "FeedbackRecord", back_populates="actions"
    )
