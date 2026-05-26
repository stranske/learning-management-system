"""Tests for durable review schedule records."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from lms.scheduling.models import ReviewSchedule
from lms.scheduling.service import seed_new_learning_item


def test_review_schedule_records_survive_queue_completion(db_session: Session) -> None:
    """Completing a queue item does not remove its durable schedule row."""
    item = seed_new_learning_item(
        db_session,
        learner_id="learner-schedule",
        knowledge_node_id="node-schedule",
    )
    item.status = "completed"
    db_session.commit()

    schedule = db_session.scalar(
        select(ReviewSchedule).where(ReviewSchedule.review_queue_item_id == item.id)
    )

    assert schedule is not None
    assert schedule.learner_id == "learner-schedule"
    assert schedule.knowledge_node_id == "node-schedule"
    assert schedule.reason_code == "new-learning"
    assert schedule.schedule_state == "scheduled"
    assert schedule.review_queue_item_id == item.id
