"""SQLAlchemy models for learner attempts and evidence inputs."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, CheckConstraint, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from lms.auth.models import new_uuid, utc_now
from lms.db.base import Base

SUPPORT_LEVELS: tuple[str, ...] = ("none", "hint", "reference", "worked-example", "coach")


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
        Boolean, nullable=False, default=False, server_default="0", index=True
    )
    hint_used: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
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
