"""Tests for capability target API routes."""

from __future__ import annotations

from typing import Any, cast

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from lms.auth.models import User
from lms.capability.repository import create_capability_target
from lms.competencies.repository import create_competency
from lms.db.session import get_session
from lms.graphs.repository import create_knowledge_node
from lms.learners.repository import create_learner_for_user, create_learning_goal
from lms.main import create_app


def _client(db_session: Session) -> TestClient:
    app = create_app(enable_local_identity_routes=True)
    app.dependency_overrides[get_session] = lambda: db_session
    return TestClient(app)


def _fixtures(db_session: Session) -> dict[str, str]:
    user = User(
        email="api-learner@example.test",
        username="api-learner",
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
        title="Explain evidence tradeoffs",
        knowledge_type="judgment",
        scope="personal",
        actor_id="user:alice",
        status="published",
    )
    goal = create_learning_goal(
        db_session,
        learner_id=learner.id,
        title="Evidence reasoning",
        knowledge_type="judgment",
        target_node_ids=[node.id],
        ownership_scope="personal",
    )
    competency = create_competency(
        db_session,
        title="Evidence-backed judgment",
        ownership_scope="personal",
        target_knowledge_type="judgment",
        status="active",
    )
    db_session.commit()
    return {
        "learner_id": learner.id,
        "node_id": node.id,
        "goal_id": goal.id,
        "competency_id": competency.id,
    }


def test_create_personal_capability_target_with_nodes_and_competencies(
    db_session: Session,
) -> None:
    """The API creates and lists personal capability targets."""
    client = _client(db_session)
    ids = _fixtures(db_session)

    response = client.post(
        "/capability/targets",
        json={
            "learner_id": ids["learner_id"],
            "title": "Reach evidence-backed judgment",
            "learning_goal_id": ids["goal_id"],
            "target_node_ids": [ids["node_id"]],
            "target_competency_ids": [ids["competency_id"]],
            "required_evidence_types": ["rubric-score"],
            "confidence_threshold": 0.82,
        },
    )

    assert response.status_code == 201, response.text
    payload = cast(dict[str, Any], response.json())
    assert payload["ownership_scope"] == "personal"
    assert payload["learner_id"] == ids["learner_id"]
    assert payload["target_node_ids"] == [ids["node_id"]]
    assert payload["target_competency_ids"] == [ids["competency_id"]]

    list_response = client.get(
        "/capability/targets",
        params={"learner_id": ids["learner_id"]},
    )
    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()] == [payload["id"]]


def test_capability_target_rejects_institutional_scope_request(db_session: Session) -> None:
    """Institutional target creation is rejected by the API contract."""
    client = _client(db_session)
    ids = _fixtures(db_session)

    response = client.post(
        "/capability/targets",
        json={
            "learner_id": ids["learner_id"],
            "title": "Institutional target",
            "ownership_scope": "institutional",
            "target_node_ids": [ids["node_id"]],
        },
    )

    assert response.status_code == 422
    assert "personal" in response.text


def test_patch_and_archive_capability_target(db_session: Session) -> None:
    """The API updates and archives target records."""
    client = _client(db_session)
    ids = _fixtures(db_session)
    target = create_capability_target(
        db_session,
        learner_id=ids["learner_id"],
        title="Initial target",
        target_node_ids=[ids["node_id"]],
    )
    db_session.commit()

    patch_response = client.patch(
        f"/capability/targets/{target.id}",
        json={"title": "Revised target", "required_evidence_types": ["attempt"]},
    )
    assert patch_response.status_code == 200, patch_response.text
    assert patch_response.json()["title"] == "Revised target"

    archive_response = client.post(f"/capability/targets/{target.id}/archive")
    assert archive_response.status_code == 200
    assert archive_response.json()["status"] == "archived"
