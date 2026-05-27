"""Tests for feedback API routes."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from lms.db.session import get_session
from lms.main import create_app


def _client(db_session: Session) -> TestClient:
    app = create_app(enable_local_identity_routes=True)
    app.dependency_overrides[get_session] = lambda: db_session
    return TestClient(app)


def test_create_feedback_action_for_remediation(db_session: Session) -> None:
    """Feedback action API persists remediation next actions and exposes filters."""
    client = _client(db_session)
    record_response = client.post(
        "/feedback",
        json={
            "learner_id": "learner-1",
            "prompt_id": "prompt-1",
            "feedback_level": "remediation",
            "goal": "Solve equations and verify the solution.",
            "observed_evidence": "Isolated x correctly.",
            "gap": "Needs a substitution check.",
        },
    )
    assert record_response.status_code == 201
    feedback_record_id = record_response.json()["id"]

    action_response = client.post(
        "/feedback-actions",
        json={
            "learner_id": "learner-1",
            "feedback_record_id": feedback_record_id,
            "prompt_id": "prompt-1",
            "action_type": "prerequisite-remediation",
            "title": "Retry with a substitution check.",
            "instructions": "Show the substitution after solving.",
        },
    )
    assert action_response.status_code == 201
    action = action_response.json()
    assert action["status"] == "open"
    assert action["feedback_record_id"] == feedback_record_id

    list_response = client.get(
        "/feedback-actions",
        params={
            "learner_id": "learner-1",
            "feedback_record_id": feedback_record_id,
            "action_type": "prerequisite-remediation",
        },
    )
    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()] == [action["id"]]

    parent_response = client.get(f"/feedback/{feedback_record_id}")
    assert parent_response.status_code == 200
    assert parent_response.json()["next_action_ids"] == [action["id"]]


def test_create_feedback_rejects_unknown_attempt_id(db_session: Session) -> None:
    """Feedback creation returns 404 when the referenced attempt does not exist."""
    client = _client(db_session)
    response = client.post(
        "/feedback",
        json={
            "learner_id": "learner-1",
            "attempt_id": "00000000-0000-0000-0000-000000000000",
            "goal": "Solve equations and verify the solution.",
            "observed_evidence": "Isolated x correctly.",
        },
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Referenced attempt not found."


def test_create_feedback_rejects_unknown_evidence_record_id(db_session: Session) -> None:
    """Feedback creation returns 404 when the referenced evidence record does not exist."""
    client = _client(db_session)
    response = client.post(
        "/feedback",
        json={
            "learner_id": "learner-1",
            "evidence_record_id": "00000000-0000-0000-0000-000000000000",
            "goal": "Solve equations and verify the solution.",
            "observed_evidence": "Isolated x correctly.",
        },
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Referenced evidence record not found."


def test_create_feedback_action_rejects_unknown_feedback_record_id(db_session: Session) -> None:
    """Feedback action creation returns 404 when the parent record does not exist."""
    client = _client(db_session)
    response = client.post(
        "/feedback-actions",
        json={
            "learner_id": "learner-1",
            "feedback_record_id": "00000000-0000-0000-0000-000000000000",
            "action_type": "retry",
            "title": "Retry.",
        },
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Referenced feedback record not found."


def test_openapi_schema_includes_feedback_routes(db_session: Session) -> None:
    """Feedback routes are included in the public API schema."""
    client = _client(db_session)

    schema = client.get("/openapi.json").json()

    assert "/feedback" in schema["paths"]
    assert "/feedback-actions" in schema["paths"]
    assert "/revision-requests" in schema["paths"]
    assert "/feedback/{feedback_record_id}/revision-requests" in schema["paths"]
