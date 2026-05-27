"""SQLAlchemy models for durable learner feedback, rubrics, and actions."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from lms.auth.models import new_uuid, utc_now
from lms.db.base import Base


def _sql_values(values: tuple[str, ...]) -> str:
    """Return SQL string literals for a check constraint."""
    return ", ".join(f"'{value}'" for value in values)


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
RUBRIC_STATUSES: tuple[str, ...] = ("draft", "published", "archived")
RUBRIC_CRITERION_STATUSES: tuple[str, ...] = ("active", "archived")
MISCONCEPTION_ACTION_TYPES: tuple[str, ...] = FEEDBACK_ACTION_TYPES
FEEDBACK_TEMPLATE_STATUSES: tuple[str, ...] = ("draft", "published", "archived")


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


class MisconceptionPattern(Base):
    """Deterministic misconception catalog entry for local feedback rules."""

    __tablename__ = "misconception_patterns"
    __table_args__ = (
        CheckConstraint(
            "ownership_scope IN ('personal', 'institutional')",
            name="misconception_pattern_ownership_scope_valid",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0)",
            name="misconception_pattern_confidence_unit_interval",
        ),
        CheckConstraint(
            f"suggested_feedback_action_type IN ({_sql_values(MISCONCEPTION_ACTION_TYPES)})",
            name="misconception_pattern_action_type_valid",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    pattern_label: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    wrong_answer_signature: Mapped[str] = mapped_column(Text, nullable=False)
    diagnosis_text: Mapped[str] = mapped_column(Text, nullable=False)
    target_knowledge_node_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("knowledge_nodes.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    ownership_scope: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    confidence: Mapped[float | None] = mapped_column(Float)
    suggested_feedback_action_type: Mapped[str] = mapped_column(String(64), nullable=False)
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


class FeedbackTemplate(Base):
    """Reusable deterministic feedback language for author-managed patterns."""

    __tablename__ = "feedback_templates"
    __table_args__ = (
        CheckConstraint(
            "ownership_scope IN ('personal', 'institutional')",
            name="feedback_template_ownership_scope_valid",
        ),
        CheckConstraint(
            f"feedback_level IN ({_sql_values(FEEDBACK_LEVELS)})",
            name="feedback_template_level_valid",
        ),
        CheckConstraint(
            f"action_type IN ({_sql_values(FEEDBACK_ACTION_TYPES)})",
            name="feedback_template_action_type_valid",
        ),
        CheckConstraint(
            f"status IN ({_sql_values(FEEDBACK_TEMPLATE_STATUSES)})",
            name="feedback_template_status_valid",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    template_body: Mapped[str] = mapped_column(Text, nullable=False)
    placeholder_schema: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    feedback_level: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    action_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    ownership_scope: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="draft",
        server_default=text("'draft'"),
        index=True,
    )
    authoring_actor: Mapped[str] = mapped_column(String(255), nullable=False)
    misconception_pattern_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("misconception_patterns.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    feedback_action_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("feedback_actions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    knowledge_node_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
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


class Rubric(Base):
    """A performance standard that can be linked to prompts, nodes, or later cases."""

    __tablename__ = "rubrics"
    __table_args__ = (
        CheckConstraint(
            "ownership_scope IN ('personal', 'institutional')",
            name="rubric_ownership_scope_valid",
        ),
        CheckConstraint(
            f"status IN ({_sql_values(RUBRIC_STATUSES)})",
            name="rubric_status_valid",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    ownership_scope: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    prompt_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("prompts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    knowledge_node_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("knowledge_nodes.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    case_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="draft",
        server_default=text("'draft'"),
        index=True,
    )
    authoring_actor: Mapped[str] = mapped_column(String(255), nullable=False)
    reviewing_actor: Mapped[str | None] = mapped_column(String(255))
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

    criteria: Mapped[list[RubricCriterion]] = relationship(
        "RubricCriterion",
        back_populates="rubric",
        cascade="all, delete-orphan",
        order_by="RubricCriterion.criterion_order",
    )


class RubricCriterion(Base):
    """One ordered criterion within a rubric."""

    __tablename__ = "rubric_criteria"
    __table_args__ = (
        CheckConstraint("criterion_order >= 1", name="rubric_criterion_order_positive"),
        CheckConstraint("max_points > 0", name="rubric_criterion_max_points_positive"),
        CheckConstraint(
            f"status IN ({_sql_values(RUBRIC_CRITERION_STATUSES)})",
            name="rubric_criterion_status_valid",
        ),
        UniqueConstraint("rubric_id", "criterion_order", name="rubric_criterion_order_unique"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    rubric_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("rubrics.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    criterion_order: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    max_points: Mapped[float] = mapped_column(Float, nullable=False)
    performance_levels: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    validity_scope: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="active",
        server_default=text("'active'"),
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
        onupdate=utc_now,
        server_default=func.now(),
        nullable=False,
    )

    rubric: Mapped[Rubric] = relationship("Rubric", back_populates="criteria")


class RubricScore(Base):
    """Criterion-level scoring result for one learner attempt."""

    __tablename__ = "rubric_scores"
    __table_args__ = (
        CheckConstraint("raw_score >= 0", name="rubric_score_raw_non_negative"),
        CheckConstraint("max_score > 0", name="rubric_score_max_positive"),
        CheckConstraint(
            "normalized_score >= 0.0 AND normalized_score <= 1.0",
            name="rubric_score_normalized_unit_interval",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    rubric_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("rubrics.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    attempt_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("attempts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    learner_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    scorer_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    scorer_id: Mapped[str | None] = mapped_column(String(255))
    scorer_version: Mapped[str | None] = mapped_column(String(120))
    raw_score: Mapped[float] = mapped_column(Float, nullable=False)
    normalized_score: Mapped[float] = mapped_column(Float, nullable=False, index=True)
    max_score: Mapped[float] = mapped_column(Float, nullable=False)
    criterion_scores: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    evidence_record_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("evidence_records.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    feedback_record_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("feedback_records.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    score_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        nullable=False,
        index=True,
    )

    rubric: Mapped[Rubric] = relationship("Rubric")
