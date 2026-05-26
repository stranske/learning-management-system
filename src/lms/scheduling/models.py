"""SQLAlchemy models for the review queue scheduler."""

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
    String,
    Text,
    func,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from lms.auth.models import new_uuid, utc_now
from lms.db.base import Base
from lms.evidence.models import SUPPORT_LEVELS
from lms.graphs.models import KNOWLEDGE_TYPES, OWNERSHIP_SCOPES

REASON_CODES: tuple[str, ...] = (
    "new-learning",
    "due-review",
    "overdue",
    "remediation",
    "stale",
    "blocked-prerequisite",
)
QUEUE_STATUSES: tuple[str, ...] = ("pending", "dispatched", "completed", "skipped")
SCHEDULE_STATES: tuple[str, ...] = ("scheduled", "completed", "skipped", "stale")


def _sql_values(values: tuple[str, ...]) -> str:
    """Return SQL string literals for a check constraint."""
    return ", ".join(f"'{value}'" for value in values)


class ReviewQueueItem(Base):
    """A scheduled review, remediation, or new-learning item for a learner."""

    __tablename__ = "review_queue_items"
    __table_args__ = (
        CheckConstraint(
            f"reason_code IN ({_sql_values(REASON_CODES)})",
            name="reason_code_valid",
        ),
        CheckConstraint(
            f"status IN ({_sql_values(QUEUE_STATUSES)})",
            name="status_valid",
        ),
        CheckConstraint(
            "priority >= 0.0 AND priority <= 1.0",
            name="priority_unit_interval",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    learner_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    knowledge_node_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    reason_explanation: Mapped[str] = mapped_column(Text, nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    priority: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending",
        server_default="pending",
        index=True,
    )
    source_attempt_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("attempts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_evidence_record_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("evidence_records.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    decision_log: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
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
        server_default=func.now(),
        onupdate=utc_now,
        nullable=False,
    )


class ReviewPolicy(Base):
    """Durable scheduler policy metadata used to explain queue decisions."""

    __tablename__ = "review_policies"
    __table_args__ = (
        CheckConstraint(
            f"reason_code IN ({_sql_values(REASON_CODES)})",
            name="review_policy_reason_code_valid",
        ),
        CheckConstraint(
            f"knowledge_type IS NULL OR knowledge_type IN ({_sql_values(KNOWLEDGE_TYPES)})",
            name="review_policy_knowledge_type_valid",
        ),
        CheckConstraint(
            f"ownership_scope IS NULL OR ownership_scope IN ({_sql_values(OWNERSHIP_SCOPES)})",
            name="review_policy_ownership_scope_valid",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    knowledge_type: Mapped[str | None] = mapped_column(String(32), index=True)
    ownership_scope: Mapped[str | None] = mapped_column(String(32), index=True)
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=true(),
        index=True,
    )
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
        server_default=func.now(),
        onupdate=utc_now,
        nullable=False,
    )


class ReviewSchedule(Base):
    """Durable schedule record that can outlive queue item churn."""

    __tablename__ = "review_schedules"
    __table_args__ = (
        CheckConstraint(
            f"reason_code IN ({_sql_values(REASON_CODES)})",
            name="review_schedule_reason_code_valid",
        ),
        CheckConstraint(
            f"schedule_state IN ({_sql_values(SCHEDULE_STATES)})",
            name="review_schedule_state_valid",
        ),
        CheckConstraint(
            f"knowledge_type IS NULL OR knowledge_type IN ({_sql_values(KNOWLEDGE_TYPES)})",
            name="review_schedule_knowledge_type_valid",
        ),
        CheckConstraint(
            f"ownership_scope IS NULL OR ownership_scope IN ({_sql_values(OWNERSHIP_SCOPES)})",
            name="review_schedule_ownership_scope_valid",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    learner_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    knowledge_node_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    review_policy_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("review_policies.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    review_queue_item_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("review_queue_items.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    schedule_state: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="scheduled",
        server_default="scheduled",
        index=True,
    )
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    knowledge_type: Mapped[str | None] = mapped_column(String(32), index=True)
    ownership_scope: Mapped[str | None] = mapped_column(String(32), index=True)
    source_evidence_record_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("evidence_records.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
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
        server_default=func.now(),
        onupdate=utc_now,
        nullable=False,
    )


class SchedulerDecision(Base):
    """Explainable scheduler decision linked to schedule, evidence, and queue context."""

    __tablename__ = "scheduler_decisions"
    __table_args__ = (
        CheckConstraint(
            f"reason_code IN ({_sql_values(REASON_CODES)})",
            name="scheduler_decision_reason_code_valid",
        ),
        CheckConstraint(
            f"knowledge_type IS NULL OR knowledge_type IN ({_sql_values(KNOWLEDGE_TYPES)})",
            name="scheduler_decision_knowledge_type_valid",
        ),
        CheckConstraint(
            f"ownership_scope IS NULL OR ownership_scope IN ({_sql_values(OWNERSHIP_SCOPES)})",
            name="scheduler_decision_ownership_scope_valid",
        ),
        CheckConstraint(
            f"support_level IS NULL OR support_level IN ({_sql_values(SUPPORT_LEVELS)})",
            name="scheduler_decision_support_level_valid",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    learner_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    knowledge_node_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    review_policy_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("review_policies.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    review_schedule_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("review_schedules.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    review_queue_item_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("review_queue_items.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_evidence_record_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("evidence_records.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    decision_rationale: Mapped[str] = mapped_column(Text, nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    knowledge_type: Mapped[str | None] = mapped_column(String(32), index=True)
    ownership_scope: Mapped[str | None] = mapped_column(String(32), index=True)
    support_level: Mapped[str | None] = mapped_column(String(32), index=True)
    decision_log: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        nullable=False,
        index=True,
    )
