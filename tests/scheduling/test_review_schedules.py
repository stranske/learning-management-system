"""Tests for durable review schedule records."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from lms.graphs.repository import create_knowledge_node
from lms.scheduling.models import REMEDIATION_TRIGGER_TYPES, ReviewSchedule
from lms.scheduling.repository import create_remediation_trigger, list_remediation_triggers
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


@pytest.mark.parametrize("trigger_type", ["invalid", "", "FAILED-PREREQUISITE"])
def test_remediation_repository_rejects_unknown_types_without_rollback(
    db_session: Session, trigger_type: str
) -> None:
    """Invalid triggers do not poison the session or remove an earlier trigger."""
    node = create_knowledge_node(
        db_session,
        title="Trigger validation",
        knowledge_type="conceptual",
        scope="personal",
        actor_id="user:alice",
    )
    existing = create_remediation_trigger(
        db_session,
        knowledge_node_id=node.id,
        trigger_type="failed-prerequisite",
        trigger_rules={"prerequisite_node_id": "node-prereq"},
        ownership_scope="personal",
    )
    with pytest.raises(ValueError, match="unknown trigger_type"):
        create_remediation_trigger(
            db_session,
            knowledge_node_id=node.id,
            trigger_type=trigger_type,
            trigger_rules={},
            ownership_scope="personal",
        )

    assert db_session.is_active
    assert not db_session.new
    assert not db_session.dirty
    assert list_remediation_triggers(db_session, knowledge_node_id=node.id) == [existing]
    valid = create_remediation_trigger(
        db_session,
        knowledge_node_id=node.id,
        trigger_type="manual-author-flag",
        trigger_rules={"note": "valid after rejection"},
        ownership_scope="personal",
    )
    db_session.commit()
    db_session.refresh(existing)
    db_session.refresh(valid)
    assert existing.trigger_rules == {"prerequisite_node_id": "node-prereq"}
    assert len(list_remediation_triggers(db_session, knowledge_node_id=node.id)) == 2


@pytest.mark.parametrize("trigger_type", REMEDIATION_TRIGGER_TYPES)
def test_remediation_repository_accepts_supported_types(
    db_session: Session, trigger_type: str
) -> None:
    node = create_knowledge_node(
        db_session,
        title="Valid trigger",
        knowledge_type="conceptual",
        scope="personal",
        actor_id="user:alice",
    )
    trigger = create_remediation_trigger(
        db_session,
        knowledge_node_id=node.id,
        trigger_type=trigger_type,
        trigger_rules={"rule": "test"},
        ownership_scope="personal",
    )
    db_session.commit()
    db_session.refresh(trigger)
    assert trigger.trigger_type == trigger_type
