"""Tests for capability gap analysis API routes."""

from __future__ import annotations

from typing import Any, cast

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from lms.auth.models import User
from lms.capability.repository import create_capability_target, recompute_capability_estimate
from lms.db.session import get_session
from lms.evidence.repository import create_evidence_record
from lms.graphs.repository import create_knowledge_node
from lms.learners.repository import create_learner_for_user
from lms.main import create_app


def _client(db_session: Session) -> TestClient:
    app = create_app(enable_local_identity_routes=True)
    app.dependency_overrides[get_session] = lambda: db_session
    return TestClient(app)


def test_create_gap_analysis_from_estimate(db_session: Session) -> None:
    """The API creates, lists, and reads persisted gap analyses."""
    client = _client(db_session)
    user = User(
        email="gap-api@example.test",
        username="gap-api",
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
        title="Explain tradeoffs",
        knowledge_type="conceptual",
        scope="personal",
        actor_id=user.id,
        status="published",
    )
    create_evidence_record(
        db_session,
        learner_id=learner.id,
        knowledge_node_id=node.id,
        knowledge_type="conceptual",
        normalized_score=0.45,
    )
    target = create_capability_target(
        db_session,
        learner_id=learner.id,
        title="Explain tradeoffs",
        target_node_ids=[node.id],
        required_evidence_types=["rubric-score"],
        confidence_threshold=0.8,
    )
    estimate = recompute_capability_estimate(db_session, target_id=target.id)
    db_session.commit()

    response = client.post("/capability/gap-analyses", json={"estimate_id": estimate.id})

    assert response.status_code == 201, response.text
    payload = cast(dict[str, Any], response.json())
    assert payload["target_id"] == target.id
    assert payload["estimate_id"] == estimate.id
    assert payload["learner_id"] == learner.id
    assert payload["ownership_scope"] == "personal"
    assert payload["severity"] == "high"
    assert payload["required_evidence"] == ["rubric-score"]
    assert "remediation-practice" in payload["recommended_action_types"]
    assert payload["gap_items"][0]["knowledge_node_id"] == node.id

    list_response = client.get("/capability/gap-analyses", params={"target_id": target.id})
    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()] == [payload["id"]]

    detail_response = client.get(f"/capability/gap-analyses/{payload['id']}")
    assert detail_response.status_code == 200
    assert detail_response.json()["id"] == payload["id"]
