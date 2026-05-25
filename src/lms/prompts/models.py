"""SQLAlchemy models for source-grounded retrieval prompts."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from lms.auth.models import new_uuid, utc_now
from lms.db.base import Base
from lms.graphs.models import KNOWLEDGE_TYPES, _sql_values

if TYPE_CHECKING:
    from lms.graphs.models import KnowledgeNode
    from lms.learners.models import LearningGoal
    from lms.sources.models import SourceReference


COGNITIVE_ACTIONS: tuple[str, ...] = (
    "recall",
    "explain",
    "apply",
    "analyze",
    "evaluate",
    "create",
)
DEMAND_LEVELS: tuple[str, ...] = ("low", "medium", "high")
ANSWER_FORMS: tuple[str, ...] = (
    "short-text",
    "long-text",
    "multiple-choice",
    "worked-example",
    "oral-response",
)
PROMPT_STATUSES: tuple[str, ...] = ("draft", "in-review", "published", "archived")
AUTHORING_METHODS: tuple[str, ...] = ("human-authored", "llm-generated", "imported")

prompt_source_references = Table(
    "prompt_source_references",
    Base.metadata,
    Column(
        "prompt_id",
        String(36),
        ForeignKey("prompts.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "source_reference_id",
        String(36),
        ForeignKey("source_references.id", ondelete="RESTRICT"),
        primary_key=True,
    ),
)


class Prompt(Base):
    """A source-cited retrieval prompt with provenance and publication state."""

    __tablename__ = "prompts"
    __table_args__ = (
        CheckConstraint(
            f"knowledge_type IN ({_sql_values(KNOWLEDGE_TYPES)})",
            name="knowledge_type_valid",
        ),
        CheckConstraint(
            f"intended_cognitive_action IN ({_sql_values(COGNITIVE_ACTIONS)})",
            name="intended_cognitive_action_valid",
        ),
        CheckConstraint(
            f"demand_level IN ({_sql_values(DEMAND_LEVELS)})",
            name="demand_level_valid",
        ),
        CheckConstraint(
            f"expected_answer_form IN ({_sql_values(ANSWER_FORMS)})",
            name="expected_answer_form_valid",
        ),
        CheckConstraint(
            f"status IN ({_sql_values(PROMPT_STATUSES)})",
            name="status_valid",
        ),
        CheckConstraint(
            f"authoring_method IN ({_sql_values(AUTHORING_METHODS)})",
            name="authoring_method_valid",
        ),
        CheckConstraint(
            "status != 'published' OR (reviewing_actor IS NOT NULL AND approval_timestamp IS NOT NULL)",
            name="published_prompt_requires_review",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    target_node_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("knowledge_nodes.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    learning_goal_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("learning_goals.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    knowledge_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    intended_cognitive_action: Mapped[str] = mapped_column(String(32), nullable=False)
    demand_level: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    expected_answer_form: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="draft", server_default="draft", index=True
    )
    authoring_method: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    authoring_actor: Mapped[str] = mapped_column(String(255), nullable=False)
    reviewing_actor: Mapped[str | None] = mapped_column(String(255))
    approval_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    llm_model: Mapped[str | None] = mapped_column(String(120))
    prompt_template_version: Mapped[str | None] = mapped_column(String(120))
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

    target_node: Mapped[KnowledgeNode] = relationship("KnowledgeNode")
    learning_goal: Mapped[LearningGoal] = relationship("LearningGoal")
    source_references: Mapped[list[SourceReference]] = relationship(
        "SourceReference",
        secondary=prompt_source_references,
        order_by="SourceReference.id",
    )
    versions: Mapped[list[PromptVersion]] = relationship(
        "PromptVersion",
        back_populates="prompt",
        cascade="all, delete-orphan",
        order_by="PromptVersion.version_number",
    )


class PromptVersion(Base):
    """Immutable prompt wording revision."""

    __tablename__ = "prompt_versions"
    __table_args__ = (CheckConstraint("version_number >= 1", name="version_number_positive"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    prompt_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("prompts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        nullable=False,
    )

    prompt: Mapped[Prompt] = relationship("Prompt", back_populates="versions")
