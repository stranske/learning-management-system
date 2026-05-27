"""Contract tests for the expanded learner review schedule surface."""

from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from lms.auth.models import utc_now
from lms.scheduling.models import ReviewPolicy, ReviewQueueItem, ReviewSchedule, SchedulerDecision


def test_review_surface_shows_schedule_and_decision_reason(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = api_client
    now = utc_now()
    with session_factory() as session:
        policy = ReviewPolicy(
            id="policy-1",
            name="M5 spaced review",
            policy_version="m5-v1",
            reason_code="due-review",
            knowledge_type="conceptual",
            ownership_scope="personal",
            settings={"daily_cap": 3, "interval_days": 2},
        )
        queue_item = ReviewQueueItem(
            id="queue-1",
            learner_id="learner-1",
            knowledge_node_id="node-review",
            reason_code="due-review",
            reason_explanation="Re-check this concept today.",
            due_at=now,
            priority=0.82,
            source_attempt_id="attempt-1",
            decision_log={"source": "test"},
        )
        schedule = ReviewSchedule(
            id="schedule-1",
            learner_id="learner-1",
            knowledge_node_id="node-review",
            review_policy_id="policy-1",
            review_queue_item_id="queue-1",
            reason_code="due-review",
            schedule_state="scheduled",
            due_at=now + timedelta(days=2),
            policy_version="m5-v1",
            knowledge_type="conceptual",
            ownership_scope="personal",
        )
        decision = SchedulerDecision(
            id="decision-1",
            learner_id="learner-1",
            knowledge_node_id="node-review",
            review_policy_id="policy-1",
            review_schedule_id="schedule-1",
            review_queue_item_id="queue-1",
            reason_code="due-review",
            decision_rationale="Correct on first review; checking retention.",
            policy_version="m5-v1",
            knowledge_type="conceptual",
            ownership_scope="personal",
            support_level="none",
            decision_log={"rule": "first_success"},
        )
        session.add_all([policy, queue_item, schedule, decision])
        session.commit()

    response = client.get("/app/learner/reviews?learner_id=learner-1&daily_cap=10")

    assert response.status_code == 200
    html = response.text
    assert "Schedule detail" in html
    assert "Scheduler decisions" in html
    assert "Review policy" in html
    assert "Correct on first review; checking retention." in html
    assert "M5 spaced review" in html
    assert "daily_cap: 3" in html
    assert "Open attempt" in html
    assert 'data-action="pause-review" disabled' in html
    assert 'name="viewport"' in html


def test_review_surface_handles_empty_and_blocked_states(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = api_client
    with session_factory() as session:
        session.add(
            ReviewSchedule(
                id="schedule-blocked",
                learner_id="learner-2",
                knowledge_node_id="node-blocked",
                reason_code="blocked-prerequisite",
                schedule_state="scheduled",
                due_at=utc_now(),
                policy_version="m5-v1",
                knowledge_type="conceptual",
                ownership_scope="personal",
            )
        )
        session.commit()

    blocked_response = client.get("/app/learner/reviews?learner_id=learner-2")
    empty_response = client.get("/app/learner/reviews?learner_id=learner-empty")

    assert blocked_response.status_code == 200
    assert "All review items are blocked by prerequisites." in blocked_response.text
    assert "blocked-prerequisite" in blocked_response.text
    assert empty_response.status_code == 200
    assert "No due review items." in empty_response.text
    assert "No durable review schedules." in empty_response.text
