"""Tests for feedback template API routes."""

from __future__ import annotations

from typing import Any, cast

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from lms.db.session import get_session
from lms.main import create_app


def _client(db_session: Session) -> TestClient:
    app = create_app(enable_local_identity_routes=True)
    app.dependency_overrides[get_session] = lambda: db_session
    return TestClient(app)


def _payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "Goal-gap-next action",
        "template_body": "Goal: {goal}\nGap: {gap}\nNext: {next_action}",
        "placeholder_schema": {"required": ["goal", "gap", "next_action"]},
        "feedback_level": "coaching",
        "action_type": "retry",
        "ownership_scope": "personal",
        "status": "published",
        "authoring_actor": "user:alice",
    }
    payload.update(overrides)
    return payload


def test_feedback_template_routes_create_render_list_and_archive(
    db_session: Session,
) -> None:
    """Feedback template API covers create, render, list, and archive workflows."""
    client = _client(db_session)

    create_response = client.post("/feedback-templates", json=_payload())

    assert create_response.status_code == 201, create_response.text
    template = cast(dict[str, Any], create_response.json())
    assert template["placeholder_schema"] == {"required": ["gap", "goal", "next_action"]}

    render_response = client.post(
        f"/feedback-templates/{template['id']}/render",
        json={
            "values": {
                "goal": "Explain denominator choices",
                "gap": "Connect the denominator to equivalent fractions",
                "next_action": "Revise with one sentence of reasoning",
            }
        },
    )
    assert render_response.status_code == 200, render_response.text
    assert "Revise with one sentence" in render_response.json()["rendered_body"]

    list_response = client.get("/feedback-templates", params={"status": "published"})
    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()] == [template["id"]]

    archive_response = client.post(f"/feedback-templates/{template['id']}/archive")
    assert archive_response.status_code == 200
    assert archive_response.json()["status"] == "archived"


def test_feedback_template_routes_reject_missing_placeholder_and_fixed_label(
    db_session: Session,
) -> None:
    """API validation reports missing placeholders and fixed-label copy."""
    client = _client(db_session)

    create_response = client.post("/feedback-templates", json=_payload())
    template = create_response.json()
    missing_response = client.post(
        f"/feedback-templates/{template['id']}/render",
        json={"values": {"goal": "Use evidence", "next_action": "Try again"}},
    )
    assert missing_response.status_code == 422
    assert "missing required placeholder values: gap" in missing_response.json()["detail"]

    fixed_label_response = client.post(
        "/feedback-templates",
        json=_payload(template_body="This weak student should {next_action}."),
    )
    assert fixed_label_response.status_code == 422
    assert "avoid fixed ability labels" in fixed_label_response.json()["detail"]
