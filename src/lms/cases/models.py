"""SQLAlchemy models for M5 transfer case shells."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from lms.auth.models import new_uuid, utc_now
from lms.db.base import Base
from lms.graphs.models import OWNERSHIP_SCOPES, _sql_values

CASE_STATUSES: tuple[str, ...] = ("draft", "published", "archived")
DECISION_POINT_TYPES: tuple[str, ...] = ("single-choice", "free-response", "evidence-selection")
WORK_PRODUCT_SUBMISSION_TYPES: tuple[str, ...] = (
    "memo",
    "rationale",
    "classification",
    "analysis",
    "artifact",
    "other",
)
WORK_PRODUCT_STATUSES: tuple[str, ...] = (
    "draft",
    "submitted",
    "scored",
    "revision-requested",
    "accepted",
    "withdrawn",
)


class Case(Base):
    """A realistic transfer case shell with source-grounded evidence."""

    __tablename__ = "cases"
    __table_args__ = (
        CheckConstraint(
            f"ownership_scope IN ({_sql_values(OWNERSHIP_SCOPES)})",
            name="case_ownership_scope_valid",
        ),
        CheckConstraint(f"status IN ({_sql_values(CASE_STATUSES)})", name="case_status_valid"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    ownership_scope: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    rubric_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("rubrics.id", ondelete="SET NULL"), index=True
    )
    knowledge_node_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("knowledge_nodes.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="draft", server_default="draft", index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        server_default=func.now(),
        nullable=False,
    )

    steps: Mapped[list[CaseStep]] = relationship(
        "CaseStep",
        back_populates="case",
        cascade="all, delete-orphan",
        order_by="CaseStep.step_order",
    )
    evidence_packets: Mapped[list[EvidencePacket]] = relationship(
        "EvidencePacket", back_populates="case", cascade="all, delete-orphan"
    )


class CaseStep(Base):
    """One ordered step in a transfer case."""

    __tablename__ = "case_steps"
    __table_args__ = (
        CheckConstraint("step_order >= 1", name="case_step_order_positive"),
        UniqueConstraint("case_id", "step_order", name="case_step_order_unique"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    case_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    expected_work_product: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )

    case: Mapped[Case] = relationship("Case", back_populates="steps")
    decision_points: Mapped[list[DecisionPoint]] = relationship(
        "DecisionPoint", back_populates="step", cascade="all, delete-orphan"
    )


class EvidencePacket(Base):
    """A packet of source references or local evidence used by a case."""

    __tablename__ = "evidence_packets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    case_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    source_reference_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("source_references.id", ondelete="SET NULL"), index=True
    )
    packet_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )

    case: Mapped[Case] = relationship("Case", back_populates="evidence_packets")


class DecisionPoint(Base):
    """A stored decision definition linked to a case step and optional evidence packet."""

    __tablename__ = "decision_points"
    __table_args__ = (
        CheckConstraint(
            f"decision_type IN ({_sql_values(DECISION_POINT_TYPES)})",
            name="decision_point_type_valid",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    case_step_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("case_steps.id", ondelete="CASCADE"), nullable=False, index=True
    )
    evidence_packet_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("evidence_packets.id", ondelete="SET NULL"), index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    decision_type: Mapped[str] = mapped_column(String(32), nullable=False)
    options: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )

    step: Mapped[CaseStep] = relationship("CaseStep", back_populates="decision_points")
    evidence_packet: Mapped[EvidencePacket | None] = relationship("EvidencePacket")


class WorkProduct(Base):
    """A learner submission for a transfer case, scored into rubric and transfer evidence."""

    __tablename__ = "work_products"
    __table_args__ = (
        CheckConstraint(
            f"submission_type IN ({_sql_values(WORK_PRODUCT_SUBMISSION_TYPES)})",
            name="work_product_submission_type_valid",
        ),
        CheckConstraint(
            f"status IN ({_sql_values(WORK_PRODUCT_STATUSES)})",
            name="work_product_status_valid",
        ),
        CheckConstraint(
            "body IS NOT NULL OR artifact_ref IS NOT NULL",
            name="work_product_body_or_artifact_present",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    case_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    case_step_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("case_steps.id", ondelete="SET NULL"), index=True
    )
    learner_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    rubric_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("rubrics.id", ondelete="SET NULL"), index=True
    )
    prompt_id: Mapped[str | None] = mapped_column(String(36), index=True)
    submission_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    body: Mapped[str | None] = mapped_column(Text)
    artifact_ref: Mapped[str | None] = mapped_column(String(1024))
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="submitted", server_default="submitted", index=True
    )
    rubric_score_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("rubric_scores.id", ondelete="SET NULL"), index=True
    )
    revision_request_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("revision_requests.id", ondelete="SET NULL"), index=True
    )
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        server_default=func.now(),
        nullable=False,
    )

    case: Mapped[Case] = relationship("Case")
