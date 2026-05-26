"""Tests for maintenance plan API routes."""

from __future__ import annotations

from typing import Any, cast

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from lms.auth.models import User
from lms.capability.repository import (
    create_capability_target,
    create_gap_analysis,
    recompute_capability_estimate,
)
from lms.db.session import get_session
from lms.evidence.repository import create_evidence_record
from lms.graphs.repository import create_knowledge_node
from lms.learners.repository import create_learner_for_user
from lms.main import create_app


def _client(db_session: Session) -> TestClient:
    app = create_app(enable_local_identity_routes=True)
    app.dependency_overrides[get_session] = lambda: db_session
    return TestClient(app)


def test_create_maintenance_plan_from_gap_analysis(db_session: Session) -> None:
    """The API creates, lists, and reads persisted maintenance plans."""
    client = _client(db_session)
    user = User(
        email="maintenance-api@example.test",
        username="maintenance-api",
        display_name="Learner",
    )
    db_session.add(user)
    db_session.flush()
    learner = create_learner_for_user(
        db_session,
        user_id=user.id,
        display_name="Learner",
    )
    node = create_knowledge_node(
        db_session,
        title="Use gap feedback",
        knowledge_type="procedural",
        scope="personal",
        actor_id=user.id,
        status="published",
    )
    create_evidence_record(
        db_session,
        learner_id=learner.id,
        knowledge_node_id=node.id,
        knowledge_type="procedural",
        normalized_score=0.25,
        correctness=False,
    )
    target = create_capability_target(
        db_session,
        learner_id=learner.id,
        title="Use gap feedback",
        target_node_ids=[node.id],
        confidence_threshold=0.8,
    )
    estimate = recompute_capability_estimate(db_session, target_id=target.id)
    analysis = create_gap_analysis(db_session, estimate_id=estimate.id)
    db_session.commit()

    response = client.post("/capability/maintenance-plans", json={"gap_analysis_id": analysis.id})

    assert response.status_code == 201, response.text
    payload = cast(dict[str, Any], response.json())
    assert payload["target_id"] == target.id
    assert payload["gap_analysis_id"] == analysis.id
    assert payload["learner_id"] == learner.id
    assert payload["ownership_scope"] == "personal"
    assert payload["status"] == "active"
    assert payload["schedule_ids"]
    assert any(step["reason_code"] == "remediation" for step in payload["plan_steps"])

    list_response = client.get(
        "/capability/maintenance-plans", params={"gap_analysis_id": analysis.id}
    )
    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()] == [payload["id"]]

    invalid_status_response = client.get(
        "/capability/maintenance-plans", params={"status": "unsupported"}
    )
    assert invalid_status_response.status_code == 422

    detail_response = client.get(f"/capability/maintenance-plans/{payload['id']}")
    assert detail_response.status_code == 200
    assert detail_response.json()["id"] == payload["id"]
