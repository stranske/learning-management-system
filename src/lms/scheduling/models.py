"""SQLAlchemy models for the review queue scheduler."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from lms.auth.models import new_uuid, utc_now
from lms.db.base import Base

REASON_CODES: tuple[str, ...] = (
    "new-learning",
    "due-review",
    "overdue",
    "remediation",
    "stale",
    "blocked-prerequisite",
)
QUEUE_STATUSES: tuple[str, ...] = ("pending", "dispatched", "completed", "skipped")


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
