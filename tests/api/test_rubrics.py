"""Tests for rubric API routes."""

from __future__ import annotations

from typing import Any, cast

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from lms.db.session import get_session
from lms.graphs.repository import create_knowledge_node
from lms.main import create_app


def _client(db_session: Session) -> TestClient:
    app = create_app(enable_local_identity_routes=True)
    app.dependency_overrides[get_session] = lambda: db_session
    return TestClient(app)


def _create_rubric(client: TestClient, **overrides: object) -> dict[str, Any]:
    payload: dict[str, object] = {
        "title": "Transfer reasoning",
        "ownership_scope": "personal",
        "authoring_actor": "user:alice",
    }
    payload.update(overrides)
    response = client.post("/rubrics", json=payload)
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


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


def test_rubric_payload_rejects_empty_optional_ids(db_session: Session) -> None:
    """Rubric create and update payloads reject blank optional link ids."""
    client = _client(db_session)

    create_response = client.post(
        "/rubrics",
        json={
            "title": "Invalid rubric",
            "ownership_scope": "personal",
            "authoring_actor": "user:alice",
            "prompt_id": "",
        },
    )

    assert create_response.status_code == 422

    rubric = _create_rubric(client)
    update_response = client.patch(f"/rubrics/{rubric['id']}", json={"prompt_id": ""})

    assert update_response.status_code == 422


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


def test_update_rubric_changes_status_and_rejects_cross_scope_link(
    db_session: Session,
) -> None:
    """PATCH /rubrics updates mutable fields and preserves scope validation."""
    client = _client(db_session)
    rubric = _create_rubric(client)

    update_response = client.patch(
        f"/rubrics/{rubric['id']}",
        json={"title": "Updated transfer rubric", "status": "published"},
    )

    assert update_response.status_code == 200, update_response.text
    updated = update_response.json()
    assert updated["title"] == "Updated transfer rubric"
    assert updated["status"] == "published"

    institutional_node = create_knowledge_node(
        db_session,
        title="Institutional standard",
        knowledge_type="judgment",
        scope="institutional",
        actor_id="user:alice",
        status="published",
    )
    db_session.commit()

    invalid_response = client.patch(
        f"/rubrics/{rubric['id']}",
        json={"knowledge_node_id": institutional_node.id},
    )

    assert invalid_response.status_code == 422
    assert "knowledge node must match" in invalid_response.json()["detail"]


def test_create_criterion_routes_validate_parent_and_unique_order(
    db_session: Session,
) -> None:
    """Criterion create routes handle missing rubrics and duplicate ordering."""
    client = _client(db_session)
    rubric = _create_rubric(
        client,
        criteria=[
            {
                "criterion_order": 1,
                "description": "States a clear claim.",
                "max_points": 2,
            }
        ],
    )

    duplicate_response = client.post(
        f"/rubrics/{rubric['id']}/criteria",
        json={
            "criterion_order": 1,
            "description": "Uses evidence.",
            "max_points": 3,
        },
    )
    assert duplicate_response.status_code == 422
    assert "criterion order must be unique" in duplicate_response.json()["detail"]

    missing_response = client.post(
        "/rubric-criteria",
        json={
            "rubric_id": "missing-rubric",
            "criterion_order": 1,
            "description": "Missing parent.",
            "max_points": 1,
        },
    )
    assert missing_response.status_code == 404
    assert "referenced rubric was not found" in missing_response.json()["detail"]


def test_update_criterion_route_validates_not_found_and_duplicate_order(
    db_session: Session,
) -> None:
    """PATCH /rubrics/{id}/criteria/{id} handles 404 and ordering violations."""
    client = _client(db_session)
    rubric = _create_rubric(
        client,
        criteria=[
            {
                "criterion_order": 1,
                "description": "States a clear claim.",
                "max_points": 2,
            },
            {
                "criterion_order": 2,
                "description": "Uses evidence.",
                "max_points": 3,
            },
        ],
    )
    second_criterion = rubric["criteria"][1]

    missing_response = client.patch(
        f"/rubrics/{rubric['id']}/criteria/missing-criterion",
        json={"description": "Still missing."},
    )
    assert missing_response.status_code == 404

    duplicate_response = client.patch(
        f"/rubrics/{rubric['id']}/criteria/{second_criterion['id']}",
        json={"criterion_order": 1},
    )
    assert duplicate_response.status_code == 422
    assert "criterion order must be unique" in duplicate_response.json()["detail"]


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
