"""The maintenance review loop: what is due, grade an answer, schedule the next.

Deliberately independent of the concept-map review queue. A maintenance item
has no ``KnowledgeNode``, so it schedules through the polymorphic card state
rather than through ``ReviewQueueItem``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from lms.auth.models import utc_now
from lms.maintenance.anchors import (
    AnchorSpec,
    GradeResult,
    grade_anchor_recall,
    grade_typicality_judgment,
)
from lms.maintenance.grading import IdeaGrader, KeyPoint, grade_idea_answer
from lms.maintenance.models import GradeDispute, MaintenanceItem
from lms.scheduling.card_state import advance_card_state, get_or_seed_card_state
from lms.scheduling.models import SUBJECT_MAINTENANCE_ITEM, ReviewCardState

# A graded answer maps onto the FSRS rating vocabulary. The thresholds are
# deliberately generous at the bottom: the point of this strand is keeping
# things reachable, not perfect reproduction.
_GOOD_SCORE = 0.85
_HARD_SCORE = 0.5


@dataclass(frozen=True)
class DueItem:
    """A maintenance item that is ready for review."""

    item: MaintenanceItem
    card: ReviewCardState | None
    due_at: datetime | None


def list_due_items(
    session: Session,
    *,
    learner_id: str,
    now: datetime | None = None,
    limit: int = 20,
) -> list[DueItem]:
    """Return active items that are due, never-reviewed items first.

    Items past their relevance horizon are excluded rather than nagging
    forever — short-dated market commentary should age out on its own.
    """
    reference = now or utc_now()
    rows = session.scalars(
        select(MaintenanceItem)
        .where(
            MaintenanceItem.learner_id == learner_id,
            MaintenanceItem.status == "active",
            or_(
                MaintenanceItem.relevant_until.is_(None),
                MaintenanceItem.relevant_until > reference,
            ),
        )
        .order_by(MaintenanceItem.created_at)
    ).all()

    due: list[DueItem] = []
    for item in rows:
        card = session.scalars(
            select(ReviewCardState).where(
                ReviewCardState.learner_id == learner_id,
                ReviewCardState.subject_type == SUBJECT_MAINTENANCE_ITEM,
                ReviewCardState.subject_id == item.id,
            )
        ).first()
        if card is None:
            due.append(DueItem(item=item, card=None, due_at=None))
            continue
        card_due = card.due_at
        if card_due is None:
            due.append(DueItem(item=item, card=card, due_at=None))
            continue
        if card_due.tzinfo is None:
            card_due = card_due.replace(tzinfo=reference.tzinfo)
        if card_due <= reference:
            due.append(DueItem(item=item, card=card, due_at=card_due))

    # Never-reviewed first, then most overdue.
    due.sort(key=lambda entry: (entry.due_at is not None, entry.due_at or reference))
    return due[:limit]


def count_active_items(session: Session, *, learner_id: str) -> int:
    """Total active items, for showing progress against the due subset."""
    return len(
        session.scalars(
            select(MaintenanceItem.id).where(
                MaintenanceItem.learner_id == learner_id,
                MaintenanceItem.status == "active",
            )
        ).all()
    )


def grade_answer(
    item: MaintenanceItem,
    answer: str,
    *,
    reading: float | None = None,
    grader: IdeaGrader | None = None,
) -> GradeResult:
    """Grade one answer according to the item's type and precision mode.

    Reference anchors grade deterministically. Idea items go to the grader
    (local Claude Code), which degrades to a labelled fallback.
    """
    if item.item_type == "reference_anchor":
        spec = AnchorSpec.from_payload(item.payload)
        if reading is not None:
            return grade_typicality_judgment(spec, answer, reading=reading)
        return grade_anchor_recall(spec, answer, precision_mode=item.precision_mode)

    key_points = [KeyPoint.from_payload(raw) for raw in item.payload.get("key_points", [])]
    return grade_idea_answer(
        prompt=item.prompt, answer=answer, key_points=key_points, grader=grader
    )


def score_to_rating(score: float) -> int:
    """Map a 0-1 grade onto the FSRS again/hard/good vocabulary.

    Never returns ``easy``: this strand maintains reachability, and awarding
    the longest possible interval off a single strong answer would push items
    out of reach faster than the owner's stated goal allows.
    """
    if score >= _GOOD_SCORE:
        return 3
    if score >= _HARD_SCORE:
        return 2
    return 1


def submit_review(
    session: Session,
    *,
    item: MaintenanceItem,
    answer: str,
    reading: float | None = None,
    grader: IdeaGrader | None = None,
    now: datetime | None = None,
) -> tuple[GradeResult, ReviewCardState]:
    """Grade an answer and advance the item's schedule. Caller commits."""
    reference = now or utc_now()
    result = grade_answer(item, answer, reading=reading, grader=grader)
    card = get_or_seed_card_state(
        session,
        learner_id=item.learner_id,
        subject_id=item.id,
        subject_type=SUBJECT_MAINTENANCE_ITEM,
        retention_tier=item.retention_tier,
        now=reference,
    )
    advance_card_state(
        session, state=card, rating_value=score_to_rating(result.score), now=reference
    )
    return result, card


def record_dispute(
    session: Session,
    *,
    item: MaintenanceItem,
    answer: str,
    machine_grade: float | None,
    learner_grade: float | None = None,
    comment: str | None = None,
    now: datetime | None = None,
) -> GradeDispute:
    """Record that the learner disagrees with a grade, and re-rate the item.

    A disputed grade should not keep driving the schedule. When the learner
    supplies their own grade we re-apply it to the card so the next interval
    reflects what they say actually happened.
    """
    reference = now or utc_now()
    dispute = GradeDispute(
        learner_id=item.learner_id,
        maintenance_item_id=item.id,
        submitted_answer=answer,
        machine_grade=machine_grade,
        learner_grade=learner_grade,
        comment=comment,
    )
    session.add(dispute)

    if learner_grade is not None:
        card = get_or_seed_card_state(
            session,
            learner_id=item.learner_id,
            subject_id=item.id,
            subject_type=SUBJECT_MAINTENANCE_ITEM,
            retention_tier=item.retention_tier,
            now=reference,
        )
        advance_card_state(
            session, state=card, rating_value=score_to_rating(learner_grade), now=reference
        )
    session.flush()
    return dispute


__all__ = [
    "DueItem",
    "count_active_items",
    "grade_answer",
    "list_due_items",
    "record_dispute",
    "score_to_rating",
    "submit_review",
]
