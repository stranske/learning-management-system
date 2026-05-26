"""HTML contract tests for the minimal Review surface."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from lms.auth.models import utc_now
from lms.scheduling.models import ReviewQueueItem


def test_review_queue_displays_reason_codes(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = api_client
    with session_factory() as session:
        session.add_all(
            [
                ReviewQueueItem(
                    learner_id="learner-1",
                    knowledge_node_id="node-1",
                    reason_code="due-review",
                    reason_explanation="Re-check this concept today.",
                    due_at=utc_now(),
                    priority=0.4,
                    decision_log={"rule": "test"},
                ),
                ReviewQueueItem(
                    learner_id="learner-1",
                    knowledge_node_id="node-2",
                    reason_code="remediation",
                    reason_explanation="Repair a missed retrieval.",
                    due_at=utc_now(),
                    priority=0.9,
                    decision_log={"rule": "test"},
                ),
            ]
        )
        session.commit()

    response = client.get("/review?learner_id=learner-1&daily_cap=10")

    assert response.status_code == 200
    html = response.text
    assert "due-review" in html
    assert "remediation" in html
    assert "Daily cap" in html
    assert 'data-action="pause-review"' in html
    assert 'data-action="mark-stale"' in html
    assert 'name="viewport"' in html


def test_canonical_review_route_displays_review_shell(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _session_factory = api_client

    response = client.get("/app/learner/review?learner_id=learner-1&daily_cap=10")

    assert response.status_code == 200
    html = response.text
    assert "<h1>Review</h1>" in html
    assert "Due review queue" in html
    assert "Review controls" in html
    assert 'href="/app/learner" aria-current="page"' in html
