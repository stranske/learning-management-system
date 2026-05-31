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


def _create_minimal_case(client: TestClient) -> dict[str, Any]:
    response = client.post(
        "/cases",
        json={
            "title": "Standalone route case",
            "description": "Created so sub-resource routes can be tested directly.",
            "ownership_scope": "personal",
        },
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


def test_standalone_case_step_route_creates_step_and_rejects_duplicate_order(
    db_session: Session,
) -> None:
    """Standalone case-step creation returns shape data and preserves duplicate-order 422s."""
    client = _client(db_session)
    case = _create_minimal_case(client)

    response = client.post(
        f"/cases/{case['id']}/steps",
        json={
            "step_order": 1,
            "title": "Find the controlling fact",
            "prompt": "Identify the fact that controls the recommendation.",
            "expected_work_product": "Controlling fact memo",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["case_id"] == case["id"]
    assert body["step_order"] == 1
    assert body["expected_work_product"] == "Controlling fact memo"

    duplicate_response = client.post(
        f"/cases/{case['id']}/steps",
        json={
            "step_order": 1,
            "title": "Duplicate order",
            "prompt": "This should be rejected.",
        },
    )
    assert duplicate_response.status_code == 422
    assert duplicate_response.json()["detail"] == "case step order must be unique"


def test_standalone_evidence_packet_route_creates_packet_and_rejects_missing_case(
    db_session: Session,
) -> None:
    """Standalone evidence-packet creation serializes metadata and keeps missing-case 422s."""
    client = _client(db_session)
    case = _create_minimal_case(client)

    response = client.post(
        f"/cases/{case['id']}/evidence-packets",
        json={
            "title": "Policy packet",
            "summary": "Facts and policy constraints.",
            "packet_metadata": {"source": "unit-test"},
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["case_id"] == case["id"]
    assert body["packet_metadata"] == {"source": "unit-test"}

    missing_response = client.post(
        "/cases/missing-case/evidence-packets",
        json={"title": "No parent"},
    )
    assert missing_response.status_code == 422
    assert missing_response.json()["detail"] == "case was not found"


def test_get_missing_case_returns_404(db_session: Session) -> None:
    """Missing case reads preserve the documented 404 detail."""
    client = _client(db_session)

    response = client.get("/cases/missing-case")

    assert response.status_code == 404
    assert response.json()["detail"] == "Case not found."


def test_list_work_products_for_missing_case_returns_404(db_session: Session) -> None:
    """Work-product listing fails before querying when the parent case is absent."""
    client = _client(db_session)

    response = client.get("/cases/missing-case/work-products")

    assert response.status_code == 404
    assert response.json()["detail"] == "Case not found."
