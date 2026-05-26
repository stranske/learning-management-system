"""SQLAlchemy models for observable competencies and evidence links."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from lms.auth.models import new_uuid, utc_now
from lms.db.base import Base
from lms.graphs.models import KNOWLEDGE_TYPES, OWNERSHIP_SCOPES

COMPETENCY_STATUSES: tuple[str, ...] = ("draft", "active", "deprecated")
EVIDENCE_ROLES: tuple[str, ...] = ("supports", "contradicts", "demonstrates", "prerequisite")


def _sql_values(values: tuple[str, ...]) -> str:
    """Return SQL string literals for a check constraint."""
    return ", ".join(f"'{value}'" for value in values)


class Competency(Base):
    """Observable capability grouping backed by graph nodes and evidence."""

    __tablename__ = "competencies"
    __table_args__ = (
        CheckConstraint(
            f"ownership_scope IN ({_sql_values(OWNERSHIP_SCOPES)})",
            name="ownership_scope_valid",
        ),
        CheckConstraint(
            f"target_knowledge_type IN ({_sql_values(KNOWLEDGE_TYPES)})",
            name="target_knowledge_type_valid",
        ),
        CheckConstraint(
            f"status IN ({_sql_values(COMPETENCY_STATUSES)})",
            name="status_valid",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    ownership_scope: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    target_knowledge_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    validity_scope: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="draft", server_default="draft", index=True
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


class CompetencyEvidence(Base):
    """Association between a competency, graph node, and learner evidence record."""

    __tablename__ = "competency_evidence"
    __table_args__ = (
        CheckConstraint(
            f"evidence_role IN ({_sql_values(EVIDENCE_ROLES)})",
            name="evidence_role_valid",
        ),
        CheckConstraint(
            "contribution_weight >= 0.0 AND contribution_weight <= 1.0",
            name="contribution_weight_unit_interval",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    competency_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("competencies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    knowledge_node_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("knowledge_nodes.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    evidence_record_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("evidence_records.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    learner_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    contribution_weight: Mapped[float] = mapped_column(
        Float, nullable=False, default=1.0, server_default="1.0"
    )
    evidence_role: Mapped[str] = mapped_column(
        String(32), nullable=False, default="supports", server_default="supports", index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        nullable=False,
        index=True,
    )

