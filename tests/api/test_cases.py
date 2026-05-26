"""Tests for transfer case API routes."""

from __future__ import annotations

from typing import Any, cast

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from lms.db.session import get_session
from lms.feedback.repository import create_rubric
from lms.graphs.repository import create_knowledge_node
from lms.main import create_app


def _client(db_session: Session) -> TestClient:
    app = create_app(enable_local_identity_routes=True)
    app.dependency_overrides[get_session] = lambda: db_session
    return TestClient(app)


def test_create_case_with_rubric_and_evidence_packet(db_session: Session) -> None:
    """Case API creates linked case shells, evidence packets, and ordered steps."""
    node = create_knowledge_node(
        db_session,
        title="Transfer node",
        knowledge_type="judgment",
        scope="personal",
        actor_id="user:alice",
        status="published",
    )
    rubric = create_rubric(
        db_session,
        title="Transfer rubric",
        ownership_scope="personal",
        authoring_actor="user:alice",
    )
    db_session.commit()
    client = _client(db_session)

    response = client.post(
        "/cases",
        json={
            "title": "Client exception case",
            "description": "Use evidence to decide whether an exception is justified.",
            "ownership_scope": "personal",
            "rubric_id": rubric.id,
            "knowledge_node_id": node.id,
            "steps": [
                {
                    "step_order": 2,
                    "title": "Recommendation",
                    "prompt": "Recommend the next action.",
                },
                {
                    "step_order": 1,
                    "title": "Evidence review",
                    "prompt": "Review the evidence packet.",
                    "expected_work_product": "Key facts list",
                },
            ],
            "evidence_packets": [
                {
                    "title": "Facts packet",
                    "summary": "Contract and policy facts.",
                    "packet_metadata": {"fixture": True},
                }
            ],
        },
    )

    assert response.status_code == 201, response.text
    body = cast(dict[str, Any], response.json())
    assert body["rubric_id"] == rubric.id
    assert body["knowledge_node_id"] == node.id
    assert [step["step_order"] for step in body["steps"]] == [1, 2]
    assert body["evidence_packets"][0]["packet_metadata"] == {"fixture": True}

    step_id = body["steps"][0]["id"]
    packet_id = body["evidence_packets"][0]["id"]
    decision_response = client.post(
        "/decision-points",
        json={
            "case_step_id": step_id,
            "evidence_packet_id": packet_id,
            "title": "Choose fact",
            "prompt": "Which fact controls the recommendation?",
            "decision_type": "evidence-selection",
            "options": [{"label": "Policy clause", "value": "policy"}],
        },
    )
    assert decision_response.status_code == 201, decision_response.text
    assert decision_response.json()["evidence_packet_id"] == packet_id

    get_response = client.get(f"/cases/{body['id']}")
    assert get_response.status_code == 200
    assert get_response.json()["steps"][0]["decision_points"][0]["title"] == "Choose fact"


def test_case_route_rejects_cross_scope_rubric(db_session: Session) -> None:
    """Case API refuses rubric links outside the case ownership scope."""
    rubric = create_rubric(
        db_session,
        title="Institutional rubric",
        ownership_scope="institutional",
        authoring_actor="user:alice",
    )
    db_session.commit()
    client = _client(db_session)

    response = client.post(
        "/cases",
        json={
            "title": "Invalid case",
            "ownership_scope": "personal",
            "rubric_id": rubric.id,
        },
    )

    assert response.status_code == 422
    assert "rubric must exist and match" in response.json()["detail"]

