"""SQLAlchemy models for personal capability targets and estimates."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    String,
    Table,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from lms.auth.models import new_uuid, utc_now
from lms.db.base import Base
from lms.graphs.models import OWNERSHIP_SCOPES, _sql_values

if TYPE_CHECKING:
    from lms.competencies.models import Competency
    from lms.graphs.models import KnowledgeNode
    from lms.learners.models import Learner, LearningGoal


CAPABILITY_TARGET_STATUSES: tuple[str, ...] = ("active", "archived")
CAPABILITY_ESTIMATE_REDACTION_CLASSES: tuple[str, ...] = (
    "learner-facing-inferred-mastery",
    "internal-inferred-mastery",
)

capability_target_nodes = Table(
    "capability_target_nodes",
    Base.metadata,
    Column(
        "capability_target_id",
        String(36),
        ForeignKey("capability_targets.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "knowledge_node_id",
        String(36),
        ForeignKey("knowledge_nodes.id", ondelete="RESTRICT"),
        primary_key=True,
    ),
)

capability_target_competencies = Table(
    "capability_target_competencies",
    Base.metadata,
    Column(
        "capability_target_id",
        String(36),
        ForeignKey("capability_targets.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "competency_id",
        String(36),
        ForeignKey("competencies.id", ondelete="RESTRICT"),
        primary_key=True,
    ),
)


class CapabilityTarget(Base):
    """Personal target that anchors capability estimates and gap plans."""

    __tablename__ = "capability_targets"
    __table_args__ = (
        CheckConstraint(
            f"ownership_scope IN ({_sql_values(OWNERSHIP_SCOPES)})",
            name="ownership_scope_valid",
        ),
        CheckConstraint("ownership_scope = 'personal'", name="personal_scope_only"),
        CheckConstraint(
            "confidence_threshold >= 0.0 AND confidence_threshold <= 1.0",
            name="confidence_threshold_unit_interval",
        ),
        CheckConstraint(
            f"status IN ({_sql_values(CAPABILITY_TARGET_STATUSES)})",
            name="status_valid",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    learner_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("learners.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    ownership_scope: Mapped[str] = mapped_column(
        String(32), nullable=False, default="personal", server_default="personal", index=True
    )
    learning_goal_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("learning_goals.id", ondelete="SET NULL"),
        index=True,
    )
    required_evidence_types: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    confidence_threshold: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.8, server_default="0.8"
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="active", server_default="active", index=True
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

    learner: Mapped[Learner] = relationship("Learner")
    learning_goal: Mapped[LearningGoal | None] = relationship("LearningGoal")
    target_nodes: Mapped[list[KnowledgeNode]] = relationship(
        "KnowledgeNode",
        secondary=capability_target_nodes,
        order_by="KnowledgeNode.id",
    )
    target_competencies: Mapped[list[Competency]] = relationship(
        "Competency",
        secondary=capability_target_competencies,
        order_by="Competency.id",
    )


class CapabilityEstimate(Base):
    """Persisted point-in-time estimate for a personal capability target."""

    __tablename__ = "capability_estimates"
    __table_args__ = (
        CheckConstraint(
            "current_score >= 0.0 AND current_score <= 1.0",
            name="current_score_unit_interval",
        ),
        CheckConstraint(
            "confidence >= 0.0 AND confidence <= 1.0",
            name="confidence_unit_interval",
        ),
        CheckConstraint(
            f"commentary_redaction_class IN ({_sql_values(CAPABILITY_ESTIMATE_REDACTION_CLASSES)})",
            name="commentary_redaction_class_valid",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    target_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("capability_targets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    learner_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("learners.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        nullable=False,
        index=True,
    )
    estimator_version: Mapped[str] = mapped_column(String(120), nullable=False)
    current_score: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    validity_scope: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_breakdown: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    weak_node_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    commentary: Mapped[str] = mapped_column(Text, nullable=False)
    commentary_redaction_class: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="learner-facing-inferred-mastery",
        server_default="learner-facing-inferred-mastery",
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        nullable=False,
    )

    target: Mapped[CapabilityTarget] = relationship("CapabilityTarget")
    learner: Mapped[Learner] = relationship("Learner")
