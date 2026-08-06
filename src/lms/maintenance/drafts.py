"""The draft approval queue.

A drafted item is a *proposal*, not content. Nothing reaches the schedule
until the owner approves it, because a wrong figure would otherwise be
memorised as fact and reinforced for years — the source documents are
scanned research PDFs with imperfect OCR, so this is a correctness control
rather than a workflow preference.

Reviewing a draft is really two jobs, and they need different care:

* **Verify the transcription.** Fields copied from the source are checked
  against the quoted snippet. Fast and mechanical.
* **Ratify the drafter's judgment.** Fields the drafter *inferred* — the
  typical band, the tolerance, the retention tier — are not in the source at
  all, and they decide how the item grades for years. This is the part worth
  actual thought, so the queue separates it visually instead of letting it
  ride along with the easy checks.

Risk-tiered rigor follows from the same reasoning: reference anchors must be
approved one at a time (a wrong number becomes a memorised falsehood) while
idea items can be approved in bulk (a weak key point degrades gracefully).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from lms.auth.models import utc_now
from lms.maintenance.models import DraftRejection, MaintenanceItem

# An unapproved draft lapses rather than accumulating. A draft you never got
# to is evidence you did not want it, and redrafting from the source is cheap.
DRAFT_TTL_DAYS: int = 30

# Hard ceiling on pending drafts. Past this, drafting REFUSES rather than
# growing a backlog — the queue must be structurally incapable of mounting,
# not merely discouraged from it.
PENDING_DRAFT_CAP: int = 40

# Default typical band as a fraction either side of the central value. Used
# when a drafter does not supply one, so the inferred part of an anchor is a
# predictable rule the owner can adjust rather than an arbitrary per-item
# guess buried in the payload.
DEFAULT_BAND_FRACTION: float = 0.25

# Payload fields an anchor draft infers rather than reads from the source.
INFERRED_ANCHOR_FIELDS: tuple[str, ...] = (
    "typical_low",
    "typical_high",
    "approximate_tolerance",
)


def default_band(
    central_value: float, *, fraction: float = DEFAULT_BAND_FRACTION
) -> tuple[float, float]:
    """Return the default typical band around a central value."""
    spread = abs(central_value) * fraction
    return (central_value - spread, central_value + spread)


@dataclass(frozen=True)
class FieldView:
    """One payload field as the reviewer sees it."""

    name: str
    value: Any
    provenance: str  # "source" | "inferred"

    @property
    def from_source(self) -> bool:
        return self.provenance == "source"


@dataclass(frozen=True)
class DraftView:
    """A draft split into what to verify and what to judge."""

    item: MaintenanceItem
    transcribed: list[FieldView]
    inferred: list[FieldView]
    expires_at: datetime | None

    @property
    def needs_individual_review(self) -> bool:
        """Anchors carry memorisable numbers, so they never bulk-approve."""
        return self.item.item_type == "reference_anchor"


def describe_draft(item: MaintenanceItem) -> DraftView:
    """Split a draft's payload into transcribed vs inferred fields."""
    provenance = dict(item.field_provenance or {})
    transcribed: list[FieldView] = []
    inferred: list[FieldView] = []
    for name, value in sorted(item.payload.items()):
        if name.startswith("_"):
            continue
        origin = provenance.get(name)
        if origin is None:
            # Unlabelled fields default to "inferred": treating an unknown
            # provenance as verified would quietly skip the review that
            # matters. Fail toward more scrutiny, not less.
            origin = "source" if name not in INFERRED_ANCHOR_FIELDS else "inferred"
            if not provenance:
                origin = "inferred"
        view = FieldView(name=name, value=value, provenance=origin)
        (transcribed if view.from_source else inferred).append(view)
    return DraftView(
        item=item,
        transcribed=transcribed,
        inferred=inferred,
        expires_at=item.draft_expires_at,
    )


def list_pending_drafts(
    session: Session, *, learner_id: str, now: datetime | None = None, limit: int = 50
) -> list[DraftView]:
    """Return drafts still awaiting a decision, oldest first."""
    reference = now or utc_now()
    items = session.scalars(
        select(MaintenanceItem)
        .where(
            MaintenanceItem.learner_id == learner_id,
            MaintenanceItem.status == "draft",
        )
        .order_by(MaintenanceItem.created_at)
    ).all()
    live = [item for item in items if not _is_expired(item, reference)]
    return [describe_draft(item) for item in live[:limit]]


def count_pending_drafts(session: Session, *, learner_id: str, now: datetime | None = None) -> int:
    """How many drafts are waiting, ignoring lapsed ones."""
    reference = now or utc_now()
    items = session.scalars(
        select(MaintenanceItem).where(
            MaintenanceItem.learner_id == learner_id,
            MaintenanceItem.status == "draft",
        )
    ).all()
    return sum(1 for item in items if not _is_expired(item, reference))


def remaining_draft_capacity(
    session: Session, *, learner_id: str, now: datetime | None = None
) -> int:
    """Slots left before drafting must refuse."""
    return max(0, PENDING_DRAFT_CAP - count_pending_drafts(session, learner_id=learner_id, now=now))


def can_accept_drafts(
    session: Session, *, learner_id: str, wanted: int = 1, now: datetime | None = None
) -> bool:
    """Whether ``wanted`` more drafts fit under the cap."""
    return remaining_draft_capacity(session, learner_id=learner_id, now=now) >= wanted


def prepare_draft(
    payload_spec: dict[str, Any],
    *,
    learner_id: str,
    now: datetime | None = None,
    ttl_days: int = DRAFT_TTL_DAYS,
) -> MaintenanceItem:
    """Build an unsaved draft with an expiry and field provenance.

    Anchor drafts get a default band derived from the central value when the
    drafter did not supply one, so the inferred part is a visible rule rather
    than an arbitrary choice.
    """
    reference = now or utc_now()
    spec = dict(payload_spec)
    payload = dict(spec.pop("payload", {}))
    provenance = dict(spec.pop("field_provenance", {}))

    if spec.get("item_type") == "reference_anchor":
        central = payload.get("central_value")
        if central is not None and (
            payload.get("typical_low") is None or payload.get("typical_high") is None
        ):
            low, high = default_band(float(central))
            payload.setdefault("typical_low", low)
            payload.setdefault("typical_high", high)
        for field in payload:
            provenance.setdefault(
                field, "inferred" if field in INFERRED_ANCHOR_FIELDS else "source"
            )

    return MaintenanceItem(
        learner_id=learner_id,
        status="draft",
        payload=payload,
        field_provenance=provenance,
        draft_expires_at=reference + timedelta(days=ttl_days),
        **spec,
    )


def approve_draft(
    session: Session,
    *,
    item: MaintenanceItem,
    payload_edits: dict[str, Any] | None = None,
    retention_tier: str | None = None,
    precision_mode: str | None = None,
    now: datetime | None = None,
) -> MaintenanceItem:
    """Approve a draft, applying any corrections made during review.

    Editing on approve is deliberate: the reviewer will often want to nudge a
    band or fix a figure, and forcing reject-and-reauthor would push them to
    approve things they only half agree with.
    """
    reference = now or utc_now()
    if payload_edits:
        payload = dict(item.payload)
        payload.update(payload_edits)
        item.payload = payload
        # An edited field is now the owner's own judgment, not the drafter's.
        provenance = dict(item.field_provenance or {})
        for field in payload_edits:
            provenance[field] = "owner-edited"
        item.field_provenance = provenance
    if retention_tier:
        item.retention_tier = retention_tier
    if precision_mode:
        item.precision_mode = precision_mode
    item.status = "active"
    item.approved_at = reference
    item.draft_expires_at = None
    session.flush()
    return item


def reject_draft(
    session: Session,
    *,
    item: MaintenanceItem,
    reason: str | None = None,
    now: datetime | None = None,
    disposition: str = "rejected",
) -> DraftRejection:
    """Discard a draft, keeping why so future drafting can improve."""
    record = DraftRejection(
        learner_id=item.learner_id,
        item_type=item.item_type,
        title=item.title,
        subject_label=item.subject_label,
        source_locator_hint=item.source_locator_hint,
        reason=(reason or "").strip() or None,
        disposition=disposition,
        created_at=now or utc_now(),
    )
    session.add(record)
    session.delete(item)
    session.flush()
    return record


def expire_stale_drafts(session: Session, *, learner_id: str, now: datetime | None = None) -> int:
    """Lapse drafts past their TTL. Returns how many were cleared."""
    reference = now or utc_now()
    items = session.scalars(
        select(MaintenanceItem).where(
            MaintenanceItem.learner_id == learner_id,
            MaintenanceItem.status == "draft",
        )
    ).all()
    expired = [item for item in items if _is_expired(item, reference)]
    for item in expired:
        reject_draft(session, item=item, reason=None, now=reference, disposition="expired")
    return len(expired)


def rejection_guidance(session: Session, *, learner_id: str, limit: int = 10) -> list[str]:
    """Recent rejection reasons, for conditioning future drafting."""
    rows = session.scalars(
        select(DraftRejection)
        .where(
            DraftRejection.learner_id == learner_id,
            DraftRejection.disposition == "rejected",
        )
        .order_by(DraftRejection.created_at.desc())
        .limit(limit)
    ).all()
    return [row.reason for row in rows if row.reason]


def _is_expired(item: MaintenanceItem, now: datetime) -> bool:
    expires = item.draft_expires_at
    if expires is None:
        return False
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=now.tzinfo)
    return expires <= now


__all__ = [
    "DEFAULT_BAND_FRACTION",
    "DRAFT_TTL_DAYS",
    "PENDING_DRAFT_CAP",
    "DraftView",
    "FieldView",
    "approve_draft",
    "can_accept_drafts",
    "count_pending_drafts",
    "default_band",
    "describe_draft",
    "expire_stale_drafts",
    "list_pending_drafts",
    "prepare_draft",
    "reject_draft",
    "rejection_guidance",
    "remaining_draft_capacity",
]
