"""HTTP error branch tests for feedback routes."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from lms.db.session import get_session
from lms.main import create_app


def _client(db_session: Session) -> TestClient:
    app = create_app(enable_local_identity_routes=True)
    app.dependency_overrides[get_session] = lambda: db_session
    return TestClient(app)


def test_get_missing_feedback_returns_404(db_session: Session) -> None:
    """Missing feedback lookups return the documented 404 detail."""
    client = _client(db_session)

    response = client.get("/feedback/missing-feedback-record")

    assert response.status_code == 404
    assert response.json()["detail"] == "Feedback not found."


def test_get_missing_feedback_action_returns_404(db_session: Session) -> None:
    """Missing feedback actions return the documented 404 detail."""
    client = _client(db_session)

    response = client.get("/feedback-actions/00000000-0000-0000-0000-000000000000")

    assert response.status_code == 404
    assert response.json()["detail"] == "Feedback action not found."


def test_list_missing_feedback_revision_requests_returns_404(db_session: Session) -> None:
    """Nested revision-request listings refuse unknown feedback ids."""
    client = _client(db_session)

    response = client.get(
        "/feedback/00000000-0000-0000-0000-000000000000/revision-requests"
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Feedback not found."


def test_get_missing_feedback_template_returns_404(db_session: Session) -> None:
    """Missing reusable feedback templates return the documented 404 detail."""
    client = _client(db_session)

    response = client.get("/feedback-templates/00000000-0000-0000-0000-000000000000")

    assert response.status_code == 404
    assert response.json()["detail"] == "Feedback template not found."


def test_render_feedback_template_missing_value_returns_422(db_session: Session) -> None:
    """Template rendering converts placeholder validation failures to HTTP 422."""
    client = _client(db_session)
    create_response = client.post(
        "/feedback-templates",
        json={
            "name": "Revision coaching",
            "template_body": "Revise the response for {learner_name}.",
            "placeholder_schema": {"required": ["learner_name"]},
            "feedback_level": "coaching",
            "action_type": "revision",
            "ownership_scope": "personal",
            "authoring_actor": "user:alice",
        },
    )
    assert create_response.status_code == 201, create_response.text
    template_id = create_response.json()["id"]

    response = client.post(
        f"/feedback-templates/{template_id}/render",
        json={"values": {}},
    )

    assert response.status_code == 422
    assert "learner_name" in response.json()["detail"]
