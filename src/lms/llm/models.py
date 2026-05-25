"""SQLAlchemy models for LLM sessions, traces, and accounting."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    false,
    func,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from lms.auth.models import new_uuid, utc_now
from lms.db.base import Base

TRACE_CLASSES: tuple[str, ...] = ("evidence-grade", "formative", "ephemeral")
LLM_MODES: tuple[str, ...] = ("study-coach", "practice", "transfer", "authoring-assist")


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
    is_replay: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        nullable=False,
    )
