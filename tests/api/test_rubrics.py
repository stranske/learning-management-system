"""Tests for rubric API routes."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from lms.db.session import get_session
from lms.graphs.repository import create_knowledge_node
from lms.main import create_app


def _client(db_session: Session) -> TestClient:
    app = create_app(enable_local_identity_routes=True)
    app.dependency_overrides[get_session] = lambda: db_session
    return TestClient(app)


def test_create_rubric_with_criteria(db_session: Session) -> None:
    """Rubric API creates nested criteria and returns deterministic ordering."""
    client = _client(db_session)
    response = client.post(
        "/rubrics",
        json={
            "title": "Transfer reasoning",
            "description": "Standards for a transfer case response.",
            "ownership_scope": "personal",
            "authoring_actor": "user:alice",
            "criteria": [
                {
                    "criterion_order": 2,
                    "description": "Uses relevant evidence.",
                    "max_points": 3,
                    "performance_levels": {"full": "Evidence is cited and explained."},
                },
                {
                    "criterion_order": 1,
                    "description": "States a defensible claim.",
                    "max_points": 2,
                    "performance_levels": {"full": "Claim is clear."},
                },
            ],
        },
    )
    assert response.status_code == 201, response.text
    rubric = response.json()
    assert rubric["status"] == "draft"
    assert [criterion["criterion_order"] for criterion in rubric["criteria"]] == [1, 2]

    get_response = client.get(f"/rubrics/{rubric['id']}")
    assert get_response.status_code == 200
    assert [criterion["criterion_order"] for criterion in get_response.json()["criteria"]] == [
        1,
        2,
    ]

    criteria_response = client.get("/rubric-criteria", params={"rubric_id": rubric["id"]})
    assert criteria_response.status_code == 200
    assert [criterion["criterion_order"] for criterion in criteria_response.json()] == [1, 2]


def test_rubric_route_rejects_cross_scope_node_link(db_session: Session) -> None:
    """Rubric creation refuses node links outside the rubric ownership scope."""
    node = create_knowledge_node(
        db_session,
        title="Institutional standard",
        knowledge_type="judgment",
        scope="institutional",
        actor_id="user:alice",
        status="published",
    )
    db_session.commit()
    client = _client(db_session)

    response = client.post(
        "/rubrics",
        json={
            "title": "Personal rubric",
            "ownership_scope": "personal",
            "knowledge_node_id": node.id,
            "authoring_actor": "user:alice",
        },
    )

    assert response.status_code == 422
    assert "knowledge node must match" in response.json()["detail"]


def test_archive_rubric_archives_criteria(db_session: Session) -> None:
    """Archive endpoint marks the rubric and its criteria archived."""
    client = _client(db_session)
    create_response = client.post(
        "/rubrics",
        json={
            "title": "Archived rubric",
            "ownership_scope": "personal",
            "authoring_actor": "user:alice",
            "criteria": [
                {
                    "criterion_order": 1,
                    "description": "Completeness",
                    "max_points": 1,
                }
            ],
        },
    )
    rubric_id = create_response.json()["id"]

    archive_response = client.post(f"/rubrics/{rubric_id}/archive")

    assert archive_response.status_code == 200
    body = archive_response.json()
    assert body["status"] == "archived"
    assert body["criteria"][0]["status"] == "archived"


def test_openapi_schema_includes_rubric_routes(db_session: Session) -> None:
    """Rubric routes are included in the public API schema."""
    client = _client(db_session)

    paths = client.get("/openapi.json").json()["paths"]

    assert "/rubrics" in paths
    assert "/rubric-criteria" in paths
