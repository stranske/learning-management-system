"""Tests for competency API routes."""

from __future__ import annotations

from typing import Any, cast

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from lms.db.session import get_session
from lms.evidence.repository import create_evidence_record
from lms.graphs.repository import create_knowledge_node
from lms.main import create_app


def _client(db_session: Session) -> TestClient:
    app = create_app(enable_local_identity_routes=True)
    app.dependency_overrides[get_session] = lambda: db_session
    return TestClient(app)


def test_create_and_list_competency_evidence(db_session: Session) -> None:
    """The API creates competencies and lists learner evidence links."""
    client = _client(db_session)
    node = create_knowledge_node(
        db_session,
        title="Diagnose misconception",
        knowledge_type="judgment",
        scope="personal",
        actor_id="user:alice",
        status="published",
    )
    evidence = create_evidence_record(
        db_session,
        learner_id="learner-api",
        knowledge_node_id=node.id,
        raw_score=4,
        normalized_score=0.8,
        max_score=5,
    )
    db_session.commit()

    competency_response = client.post(
        "/competencies",
        json={
            "title": "Misconception diagnosis",
            "ownership_scope": "personal",
            "target_knowledge_type": "judgment",
            "validity_scope": "Current learner evidence only.",
            "status": "active",
        },
    )
    assert competency_response.status_code == 201, competency_response.text
    competency = cast(dict[str, Any], competency_response.json())

    link_response = client.post(
        "/competency-evidence",
        json={
            "competency_id": competency["id"],
            "knowledge_node_id": node.id,
            "evidence_record_id": evidence.id,
            "contribution_weight": 0.8,
            "evidence_role": "supports",
        },
    )
    assert link_response.status_code == 201, link_response.text
    link = link_response.json()
    assert link["learner_id"] == "learner-api"
    assert link["contribution_weight"] == 0.8

    list_response = client.get(
        "/competency-evidence",
        params={"competency_id": competency["id"], "learner_id": "learner-api"},
    )
    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()] == [link["id"]]

    learner_response = client.get(
        f"/competencies/{competency['id']}/evidence",
        params={"learner_id": "learner-api"},
    )
    assert learner_response.status_code == 200
    assert learner_response.json()[0]["evidence_record_id"] == evidence.id


def test_competency_evidence_route_rejects_scope_mismatch(db_session: Session) -> None:
    """The API refuses evidence links across competency and node scopes."""
    client = _client(db_session)
    node = create_knowledge_node(
        db_session,
        title="Institutional standard",
        knowledge_type="conceptual",
        scope="institutional",
        actor_id="user:alice",
        status="published",
    )
    evidence = create_evidence_record(
        db_session,
        learner_id="learner-api",
        knowledge_node_id=node.id,
        raw_score=3,
        normalized_score=0.6,
        max_score=5,
    )
    db_session.commit()
    competency_response = client.post(
        "/competencies",
        json={
            "title": "Personal competency",
            "ownership_scope": "personal",
            "target_knowledge_type": "conceptual",
        },
    )
    competency_id = competency_response.json()["id"]

    response = client.post(
        "/competency-evidence",
        json={
            "competency_id": competency_id,
            "knowledge_node_id": node.id,
            "evidence_record_id": evidence.id,
        },
    )

    assert response.status_code == 422
    assert "ownership_scope must match" in response.json()["detail"]

