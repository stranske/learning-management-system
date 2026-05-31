"""Inspect overview scheduler panel coverage."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import lms.audit.models  # noqa: F401
import lms.evidence.models  # noqa: F401
import lms.graphs.models  # noqa: F401
import lms.scheduling.models  # noqa: F401
import lms.sources.models  # noqa: F401
from lms.db.base import Base
from lms.db.session import get_session
from lms.graphs.models import KnowledgeNode
from lms.main import create_app
from lms.scheduling.models import ReviewQueueItem, SchedulerDecision


@contextmanager
def _client() -> Generator[tuple[TestClient, Session], None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = session_factory()

    def override_get_session() -> Generator[Session, None, None]:
        request_session = session_factory()
        try:
            yield request_session
        finally:
            request_session.close()

    app = create_app()
    app.dependency_overrides[get_session] = override_get_session
    try:
        with TestClient(app) as client:
            yield client, session
    finally:
        session.close()
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_scheduler_panel_returns_real_data() -> None:
    due_at = datetime(2026, 5, 31, 15, 0, tzinfo=UTC)
    with _client() as (client, session):
        session.add(
            ReviewQueueItem(
                learner_id="learner-scheduler",
                knowledge_node_id="node-review",
                reason_code="due-review",
                reason_explanation="Prior retrieval is due for review.",
                due_at=due_at,
                priority=0.85,
                status="pending",
                decision_log={"rule_id": "spacing.due", "interval_days": 3},
            )
        )
        session.commit()

        response = client.get("/inspect/learners/learner-scheduler/overview")

    assert response.status_code == 200
    scheduler = response.json()["scheduler"]
    assert scheduler["status"] == "ready"
    assert scheduler["events"][0]["reason_code"] == "due-review"
    assert scheduler["events"][0]["knowledge_node_id"] == "node-review"
    assert scheduler["events"][0]["due_at"].startswith("2026-05-31T15:00:00")
    assert scheduler["events"][0]["decision_log"]["rule_id"] == "spacing.due"


def test_scheduler_panel_surfaces_recent_items_over_stale_history() -> None:
    """A learner with >10 older completed items must still see a recent pending review.

    The panel is a recent-activity debugging view (limit 10). Ordering by recency
    (``created_at`` desc) keeps current pending reviews from being crowded out by
    a backlog of older completed/skipped items with earlier ``due_at`` values.
    """
    old_created = datetime(2026, 5, 1, 9, 0, tzinfo=UTC)
    old_due = datetime(2026, 5, 1, 9, 0, tzinfo=UTC)
    recent_created = datetime(2026, 5, 31, 15, 0, tzinfo=UTC)
    recent_due = datetime(2026, 6, 15, 9, 0, tzinfo=UTC)
    with _client() as (client, session):
        for index in range(12):
            session.add(
                ReviewQueueItem(
                    learner_id="learner-backlog",
                    knowledge_node_id=f"node-old-{index}",
                    reason_code="due-review",
                    reason_explanation="Completed earlier.",
                    due_at=old_due,
                    priority=0.5,
                    status="completed",
                    created_at=old_created,
                    decision_log={"rule_id": "spacing.due"},
                )
            )
        session.add(
            ReviewQueueItem(
                learner_id="learner-backlog",
                knowledge_node_id="node-fresh",
                reason_code="due-review",
                reason_explanation="Newly scheduled review.",
                due_at=recent_due,
                priority=0.9,
                status="pending",
                created_at=recent_created,
                decision_log={"rule_id": "spacing.due"},
            )
        )
        session.commit()

        response = client.get("/inspect/learners/learner-backlog/overview")

    assert response.status_code == 200
    events = response.json()["scheduler"]["events"]
    assert len(events) == 10
    node_ids = {event["knowledge_node_id"] for event in events}
    assert "node-fresh" in node_ids


def test_scheduler_panel_honors_ownership_scope_for_decisions() -> None:
    with _client() as (client, session):
        session.add_all(
            [
                SchedulerDecision(
                    learner_id="learner-scope",
                    knowledge_node_id="node-personal",
                    reason_code="due-review",
                    decision_rationale="Personal cadence selected.",
                    policy_version="2026.05",
                    knowledge_type="factual",
                    ownership_scope="personal",
                    support_level="none",
                    decision_log={"scope": "personal"},
                ),
                SchedulerDecision(
                    learner_id="learner-scope",
                    knowledge_node_id="node-institutional",
                    reason_code="remediation",
                    decision_rationale="Institutional remediation selected.",
                    policy_version="2026.05",
                    knowledge_type="procedural",
                    ownership_scope="institutional",
                    support_level="hint",
                    decision_log={"scope": "institutional"},
                ),
            ]
        )
        session.commit()

        personal_response = client.get(
            "/inspect/learners/learner-scope/overview",
            params={"ownership_scope": "personal"},
        )
        institutional_response = client.get(
            "/inspect/learners/learner-scope/overview",
            params={"ownership_scope": "institutional"},
        )

    assert personal_response.status_code == 200
    assert institutional_response.status_code == 200

    personal_decisions = personal_response.json()["scheduler"]["decisions"]
    institutional_decisions = institutional_response.json()["scheduler"]["decisions"]
    assert {decision["knowledge_node_id"] for decision in personal_decisions} == {"node-personal"}
    assert {decision["knowledge_node_id"] for decision in institutional_decisions} == {
        "node-institutional"
    }


def test_scheduler_panel_honors_ownership_scope_for_events() -> None:
    due_at = datetime(2026, 5, 31, 15, 0, tzinfo=UTC)
    with _client() as (client, session):
        session.add_all(
            [
                KnowledgeNode(
                    id="node-personal",
                    title="Personal Node",
                    knowledge_type="factual",
                    ownership_scope="personal",
                ),
                KnowledgeNode(
                    id="node-institutional",
                    title="Institutional Node",
                    knowledge_type="procedural",
                    ownership_scope="institutional",
                ),
                ReviewQueueItem(
                    learner_id="learner-events-scope",
                    knowledge_node_id="node-personal",
                    reason_code="due-review",
                    reason_explanation="Personal review due.",
                    due_at=due_at,
                    priority=0.9,
                    status="pending",
                    decision_log={"scope": "personal"},
                ),
                ReviewQueueItem(
                    learner_id="learner-events-scope",
                    knowledge_node_id="node-institutional",
                    reason_code="remediation",
                    reason_explanation="Institutional remediation due.",
                    due_at=due_at,
                    priority=0.8,
                    status="pending",
                    decision_log={"scope": "institutional"},
                ),
            ]
        )
        session.commit()

        personal_response = client.get(
            "/inspect/learners/learner-events-scope/overview",
            params={"ownership_scope": "personal"},
        )
        institutional_response = client.get(
            "/inspect/learners/learner-events-scope/overview",
            params={"ownership_scope": "institutional"},
        )

    assert personal_response.status_code == 200
    assert institutional_response.status_code == 200
    personal_events = personal_response.json()["scheduler"]["events"]
    institutional_events = institutional_response.json()["scheduler"]["events"]
    assert {event["knowledge_node_id"] for event in personal_events} == {"node-personal"}
    assert {event["knowledge_node_id"] for event in institutional_events} == {"node-institutional"}
