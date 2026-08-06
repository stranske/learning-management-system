"""Workplace knowledge-maintenance items.

This strand is deliberately NOT concept-map driven. Its job is to keep facts a
person already learned reachable on the job — fund terms, legal clauses,
research findings — rather than to advance anyone through a prerequisite
graph. That is why these items anchor to a *source or entity* instead of
requiring a ``KnowledgeNode`` and ``LearningGoal`` the way ``Prompt`` does.

Two item types, because a research piece yields two genuinely different
things to retain (owner, 2026-08-02):

``idea``
    The argument. Graded on whether the recalled answer covers the key
    points, not on wording.

``reference_anchor``
    A number whose purpose is judging whether a *current* reading is typical
    or atypical. The useful unit is the distribution — central tendency,
    typical band, notable extremes — so these are graded on **band
    membership**, not on numeric distance. Recalling "the 25-year median is
    about 100 IPOs a year, 1999 hit roughly 400" fully supports the judgment;
    knowing the median was 97.4 adds nothing.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from lms.auth.models import new_uuid, utc_now
from lms.db.base import Base
from lms.graphs.models import _sql_values
from lms.scheduling.fsrs_engine import DEFAULT_RETENTION_TIER, RETENTION_TIERS

MAINTENANCE_ITEM_TYPES: tuple[str, ...] = ("idea", "reference_anchor")
MAINTENANCE_ITEM_STATUSES: tuple[str, ...] = ("draft", "active", "retired", "superseded")

# How exactly an answer must match. ``band`` is the default for reference
# anchors: it asks only that the learner place a reading in the right part of
# the distribution.
PRECISION_MODES: tuple[str, ...] = ("band", "approximate", "exact")
DEFAULT_PRECISION_MODE: str = "band"


class MaintenanceItem(Base):
    """One thing a learner wants to keep reachable, anchored to its source."""

    __tablename__ = "maintenance_items"
    __table_args__ = (
        CheckConstraint(
            f"item_type IN ({_sql_values(MAINTENANCE_ITEM_TYPES)})",
            name="maintenance_item_type_valid",
        ),
        CheckConstraint(
            f"status IN ({_sql_values(MAINTENANCE_ITEM_STATUSES)})",
            name="maintenance_item_status_valid",
        ),
        CheckConstraint(
            f"retention_tier IN ({_sql_values(RETENTION_TIERS)})",
            name="maintenance_item_retention_tier_valid",
        ),
        CheckConstraint(
            f"precision_mode IN ({_sql_values(PRECISION_MODES)})",
            name="maintenance_item_precision_mode_valid",
        ),
        Index("ix_maintenance_items_learner_status", "learner_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    learner_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("learners.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    item_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)

    # Source linkage. Optional so a hand-written item (a fund term you simply
    # know) does not require a document, but strongly encouraged for research
    # and legal items where "go back and read the section" is the point.
    source_reference_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("source_references.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_locator_hint: Mapped[str | None] = mapped_column(String(300))

    # Entity anchoring without a full entity table yet: a free-text subject
    # (fund, manager, document, market) that later promotes to a real entity.
    subject_label: Mapped[str | None] = mapped_column(String(200), index=True)

    retention_tier: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=DEFAULT_RETENTION_TIER,
        server_default=DEFAULT_RETENTION_TIER,
    )
    precision_mode: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=DEFAULT_PRECISION_MODE,
        server_default=DEFAULT_PRECISION_MODE,
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="draft", server_default="draft", index=True
    )

    # ``idea`` items: {"key_points": [{"label": ..., "required": true}, ...]}
    # ``reference_anchor`` items: see lms.maintenance.anchors.AnchorSpec
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    # Draft lifecycle. A drafted item is a PROPOSAL: it must be approved
    # before it can ever be scheduled, because an unverified figure would
    # otherwise be memorised as fact and reinforced for years. Unapproved
    # drafts lapse rather than accumulating — a draft you never got to is
    # evidence you did not want it, and redrafting from the source is cheap.
    draft_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Which payload fields came from the SOURCE versus which the drafter
    # inferred. The reviewer's job differs completely between the two: a
    # transcribed number is checked against the quoted snippet in seconds,
    # while an inferred band is a judgment that decides how this item grades
    # for years. Mapping field name -> "source" | "inferred".
    field_provenance: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    # Relevance horizon. Short-dated market commentary stops being worth
    # reviewing; a long-run base rate does not. Items past their horizon
    # retire instead of quietly consuming the daily budget forever.
    relevant_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    # When the *content* was true. A "25-year median" drifts as years accrue,
    # so the vintage is part of the fact, not metadata.
    content_as_of: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

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


class GradeDispute(Base):
    """A learner's objection to how an answer was graded.

    The owner asked for graded answers *with* a way to push back when the
    grading is poor. Disputes are first-class rather than a support channel:
    they correct the evidence record that drives scheduling, and they
    accumulate as training signal for the grader prompt.
    """

    __tablename__ = "grade_disputes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    learner_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("learners.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    maintenance_item_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("maintenance_items.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    evidence_record_id: Mapped[str | None] = mapped_column(String(36), index=True)
    submitted_answer: Mapped[str] = mapped_column(Text, nullable=False)
    machine_grade: Mapped[float | None] = mapped_column()
    learner_grade: Mapped[float | None] = mapped_column()
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )


class DraftRejection(Base):
    """A rejected draft, with the reason when the owner supplied one.

    Kept after the item itself is discarded so rejection reasons can
    condition future drafting — the owner asked for one-click reject plus
    optional feedback that improves what gets proposed next.
    """

    __tablename__ = "draft_rejections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    learner_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("learners.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    item_type: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    subject_label: Mapped[str | None] = mapped_column(String(200))
    source_locator_hint: Mapped[str | None] = mapped_column(String(300))
    reason: Mapped[str | None] = mapped_column(Text)
    # "rejected" when the owner said no; "expired" when it simply lapsed.
    disposition: Mapped[str] = mapped_column(
        String(16), nullable=False, default="rejected", server_default="rejected", index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=func.now(), nullable=False
    )
