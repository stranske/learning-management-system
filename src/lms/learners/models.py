"""Learner SQLAlchemy models."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, String, Table, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from lms.auth.models import new_uuid, utc_now
from lms.db.base import Base
from lms.graphs.models import KNOWLEDGE_TYPES, OWNERSHIP_SCOPES, _sql_values

if TYPE_CHECKING:
    from lms.auth.models import User
    from lms.graphs.models import KnowledgeNode


GOAL_STATUSES: tuple[str, ...] = ("active", "paused", "completed", "archived")

# A target node counts as "mastered" for goal-relative progress when its current
# mastery estimate reaches this threshold. Matches the 0.8 confidence-threshold
# default used by the capability-gap UI so the two surfaces agree on "mastered".
MASTERY_THRESHOLD: float = 0.8

learning_goal_nodes = Table(
    "learning_goal_nodes",
    Base.metadata,
    Column(
        "learning_goal_id",
        String(36),
        ForeignKey("learning_goals.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "knowledge_node_id",
        String(36),
        ForeignKey("knowledge_nodes.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class Learner(Base):
    """Learning profile owned by a user identity."""

    __tablename__ = "learners"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    display_name: Mapped[str] = mapped_column(String(200))
    timezone: Mapped[str] = mapped_column(String(80), default="UTC", nullable=False)
    locale: Mapped[str] = mapped_column(String(20), default="en-US", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        server_default=func.now(),
        nullable=False,
    )

    user: Mapped[User] = relationship("User", back_populates="learners")

    learning_goals: Mapped[list[LearningGoal]] = relationship(
        "LearningGoal",
        back_populates="learner",
        cascade="all, delete-orphan",
    )

    reflections: Mapped[list[LearnerReflection]] = relationship(
        "LearnerReflection",
        back_populates="learner",
        cascade="all, delete-orphan",
    )


class LearningGoal(Base):
    """A learner-owned objective tied to published knowledge graph nodes."""

    __tablename__ = "learning_goals"
    __table_args__ = (
        CheckConstraint(
            f"knowledge_type IN ({_sql_values(KNOWLEDGE_TYPES)})",
            name="knowledge_type_valid",
        ),
        CheckConstraint(
            f"status IN ({_sql_values(GOAL_STATUSES)})",
            name="status_valid",
        ),
        CheckConstraint(
            f"ownership_scope IN ({_sql_values(OWNERSHIP_SCOPES)})",
            name="ownership_scope_valid",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    learner_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("learners.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    knowledge_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="active", server_default="active", index=True
    )
    ownership_scope: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        server_default=func.now(),
        nullable=False,
    )

    learner: Mapped[Learner] = relationship("Learner", back_populates="learning_goals")
    target_nodes: Mapped[list[KnowledgeNode]] = relationship(
        "KnowledgeNode",
        secondary=learning_goal_nodes,
        order_by="KnowledgeNode.id",
    )


class LearnerReflection(Base):
    """A metacognitive reflection a learner records after a review.

    Stored as a small standalone record (optionally tied to the reviewed
    knowledge node) so the "reflection prompts" half of the motivation /
    self-regulation commitment is persisted and retrievable, not just scaffolded.
    """

    __tablename__ = "learner_reflections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    learner_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("learners.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    knowledge_node_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("knowledge_nodes.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    response: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        nullable=False,
        index=True,
    )

    learner: Mapped[Learner] = relationship("Learner", back_populates="reflections")
