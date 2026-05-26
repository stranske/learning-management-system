"""Repository helpers for review queue items."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from lms.scheduling.models import ReviewQueueItem


def create_review_queue_item(
    session: Session,
    *,
    learner_id: str,
    knowledge_node_id: str,
    reason_code: str,
    reason_explanation: str,
    due_at: datetime,
    decision_log: dict[str, Any],
    priority: float = 0.5,
    status: str = "pending",
    source_attempt_id: str | None = None,
    source_evidence_record_id: str | None = None,
) -> ReviewQueueItem:
    """Persist a review queue item."""
    item = ReviewQueueItem(
        learner_id=learner_id,
        knowledge_node_id=knowledge_node_id,
        reason_code=reason_code,
        reason_explanation=reason_explanation,
        due_at=due_at,
        decision_log=decision_log,
        priority=priority,
        status=status,
        source_attempt_id=source_attempt_id,
        source_evidence_record_id=source_evidence_record_id,
    )
    session.add(item)
    session.flush()
    return item


def list_review_queue_for_learner(
    session: Session,
    *,
    learner_id: str,
    status: str | None = "pending",
    limit: int = 100,
) -> Sequence[ReviewQueueItem]:
    """Return queue items for a learner ordered by due date then priority."""
    statement = select(ReviewQueueItem).where(ReviewQueueItem.learner_id == learner_id)
    if status is not None:
        statement = statement.where(ReviewQueueItem.status == status)
    statement = statement.order_by(
        ReviewQueueItem.due_at.asc(),
        ReviewQueueItem.priority.desc(),
        ReviewQueueItem.id,
    ).limit(limit)
    return list(session.scalars(statement))


def count_review_queue_for_learner(
    session: Session,
    *,
    learner_id: str,
    status: str | None = "pending",
) -> int:
    """Count queue items for a learner, optionally filtered by status."""
    statement = (
        select(func.count())
        .select_from(ReviewQueueItem)
        .where(ReviewQueueItem.learner_id == learner_id)
    )
    if status is not None:
        statement = statement.where(ReviewQueueItem.status == status)
    return int(session.scalar(statement) or 0)
