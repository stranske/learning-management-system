"""Tests for deterministic remediation triggers."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from lms.auth.models import utc_now
from lms.feedback.repository import create_misconception_pattern
from lms.graphs.repository import create_knowledge_node
from lms.scheduling.models import SchedulerDecision
from lms.scheduling.service import apply_remediation_triggers, create_failed_prerequisite_trigger
from tests.scheduling.test_review_queue import _make_attempt


def test_failed_prerequisite_trigger_schedules_remediation_reason(db_session: Session) -> None:
    """A failed prerequisite rule creates an immediate remediation decision."""
    node = create_knowledge_node(
        db_session,
        title="Fraction equivalence",
        knowledge_type="conceptual",
        scope="personal",
        actor_id="user:alice",
        status="published",
    )
    pattern = create_misconception_pattern(
        db_session,
        pattern_label="Adds denominator directly",
        wrong_answer_signature="adds denominator",
        diagnosis_text="The learner applies addition to the denominator directly.",
        target_knowledge_node_id=node.id,
        ownership_scope="personal",
        confidence=0.9,
        suggested_feedback_action_type="prerequisite-remediation",
    )
    trigger = create_failed_prerequisite_trigger(
        db_session,
        knowledge_node_id=node.id,
        ownership_scope="personal",
        pattern_id=pattern.id,
        prerequisite_node_id="node-prereq",
    )
    attempt, evidence = _make_attempt(
        db_session,
        learner_id="learner-remediation",
        knowledge_node_id=node.id,
        correctness=False,
        normalized_score=0.2,
        confidence_rating=4,
        response_metadata={"failed_prerequisite_ids": ["node-prereq"]},
    )
    fixed_now = datetime(2026, 6, 1, 12, 0, 0, tzinfo=utc_now().tzinfo)

    items = apply_remediation_triggers(
        db_session,
        attempt=attempt,
        evidence_record=evidence,
        now=fixed_now,
    )
    db_session.commit()

    assert len(items) == 1
    item = items[0]
    assert item.reason_code == "remediation"
    assert item.due_at == fixed_now
    assert item.knowledge_node_id == node.id
    assert item.decision_log["inputs"]["trigger_id"] == trigger.id

    decision = db_session.scalar(
        select(SchedulerDecision).where(SchedulerDecision.review_queue_item_id == item.id)
    )
    assert decision is not None
    assert decision.reason_code == "remediation"
    assert "failed prerequisite" in decision.decision_rationale.lower()
    assert decision.decision_log["trigger_id"] == trigger.id


def test_failed_prerequisite_trigger_requires_matching_prerequisite_signal(
    db_session: Session,
) -> None:
    """A prerequisite-scoped trigger only fires when the attempt names that prerequisite."""
    node = create_knowledge_node(
        db_session,
        title="Fraction equivalence",
        knowledge_type="conceptual",
        scope="personal",
        actor_id="user:alice",
        status="published",
    )
    create_failed_prerequisite_trigger(
        db_session,
        knowledge_node_id=node.id,
        ownership_scope="personal",
        prerequisite_node_id="node-prereq",
    )
    attempt, evidence = _make_attempt(
        db_session,
        learner_id="learner-remediation",
        knowledge_node_id=node.id,
        correctness=False,
        normalized_score=0.2,
        confidence_rating=4,
        response_metadata={"failed_prerequisite_ids": ["node-other"]},
    )
    fixed_now = datetime(2026, 6, 1, 12, 0, 0, tzinfo=utc_now().tzinfo)

    items = apply_remediation_triggers(
        db_session,
        attempt=attempt,
        evidence_record=evidence,
        now=fixed_now,
    )
    db_session.commit()

    assert items == []
