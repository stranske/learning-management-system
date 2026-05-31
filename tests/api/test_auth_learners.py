"""API tests for local auth and learners."""

from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from lms.auth.login import require_authenticated_user
from lms.auth.models import User
from lms.db.base import Base
from lms.db.session import get_session
from lms.evidence.repository import create_evidence_record
from lms.main import create_app


@pytest.mark.slow
def test_create_user_and_learner_endpoints() -> None:
    """The API can create local users and learner profiles in one app instance."""
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_session() -> Generator[Session, None, None]:
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app = create_app(enable_local_identity_routes=True)
    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[require_authenticated_user] = lambda: User(
        username="test-gate-user",
        display_name="Test Gate User",
        is_local=True,
    )
    try:
        with TestClient(app) as client:
            user_response = client.post(
                "/auth/users",
                json={
                    "username": "maria",
                    "display_name": "Maria Mitchell",
                    "email": "maria@example.test",
                },
            )
            assert user_response.status_code == 201
            user_payload = user_response.json()

            learner_response = client.post(
                "/learners",
                json={
                    "user_id": user_payload["id"],
                    "display_name": "Maria",
                    "timezone": "America/Chicago",
                },
            )
            assert learner_response.status_code == 201
            learner_payload = learner_response.json()
            assert learner_payload["user_id"] == user_payload["id"]
            assert learner_payload["display_name"] == "Maria"

            node_response = client.post(
                "/knowledge/nodes",
                json={
                    "title": "Concept mapping",
                    "knowledge_type": "conceptual",
                    "ownership_scope": "personal",
                    "status": "published",
                    "actor_id": user_payload["id"],
                },
            )
            assert node_response.status_code == 201
            node_payload = node_response.json()

            goal_response = client.post(
                f"/learners/{learner_payload['id']}/learning-goals",
                json={
                    "title": "Use concept mapping",
                    "knowledge_type": "conceptual",
                    "target_node_ids": [node_payload["id"]],
                    "ownership_scope": "personal",
                },
            )
            assert goal_response.status_code == 201
            goal_payload = goal_response.json()
            assert goal_payload["target_nodes"][0]["id"] == node_payload["id"]

            list_response = client.get(f"/learners/{learner_payload['id']}/learning-goals")
            assert list_response.status_code == 200
            assert [goal["title"] for goal in list_response.json()] == ["Use concept mapping"]

            missing_learner_response = client.post(
                "/learners/missing-learning-profile/learning-goals",
                json={
                    "title": "Should not become validation",
                    "knowledge_type": "conceptual",
                    "target_node_ids": [node_payload["id"]],
                    "ownership_scope": "personal",
                },
            )
            assert missing_learner_response.status_code == 404

            second_node_response = client.post(
                "/knowledge/nodes",
                json={
                    "title": "Retrieval planning",
                    "knowledge_type": "procedural",
                    "ownership_scope": "personal",
                    "status": "published",
                    "actor_id": user_payload["id"],
                },
            )
            assert second_node_response.status_code == 201
            second_node_payload = second_node_response.json()

            patch_response = client.patch(
                f"/learners/{learner_payload['id']}/learning-goals/{goal_payload['id']}",
                json={
                    "title": "Use retrieval planning",
                    "knowledge_type": "procedural",
                    "target_node_ids": [second_node_payload["id"]],
                    "status": "paused",
                },
            )
            assert patch_response.status_code == 200
            patched_payload = patch_response.json()
            assert patched_payload["title"] == "Use retrieval planning"
            assert patched_payload["knowledge_type"] == "procedural"
            assert patched_payload["status"] == "paused"
            assert [node["id"] for node in patched_payload["target_nodes"]] == [
                second_node_payload["id"]
            ]
            assert patched_payload["updated_at"] != goal_payload["updated_at"]

            draft_node_response = client.post(
                "/knowledge/nodes",
                json={
                    "title": "Draft target",
                    "knowledge_type": "procedural",
                    "ownership_scope": "personal",
                    "status": "draft",
                    "actor_id": user_payload["id"],
                },
            )
            assert draft_node_response.status_code == 201

            draft_patch_response = client.patch(
                f"/learners/{learner_payload['id']}/learning-goals/{goal_payload['id']}",
                json={"target_node_ids": [draft_node_response.json()["id"]]},
            )
            assert draft_patch_response.status_code == 422

            reflection_response = client.post(
                f"/learners/{learner_payload['id']}/reflections",
                json={
                    "prompt": "What made this review difficult?",
                    "response": "I mixed up retrieval planning with concept mapping.",
                    "knowledge_node_id": second_node_payload["id"],
                },
            )
            assert reflection_response.status_code == 201
            reflection_payload = reflection_response.json()
            assert reflection_payload["prompt"] == "What made this review difficult?"
            assert reflection_payload["knowledge_node_id"] == second_node_payload["id"]

            list_reflections_response = client.get(f"/learners/{learner_payload['id']}/reflections")
            assert list_reflections_response.status_code == 200
            assert [item["id"] for item in list_reflections_response.json()] == [
                reflection_payload["id"]
            ]

            with session_factory() as session:
                create_evidence_record(
                    session,
                    learner_id=learner_payload["id"],
                    knowledge_node_id=second_node_payload["id"],
                    knowledge_type="procedural",
                    normalized_score=0.95,
                )
                session.commit()

            progress_response = client.get(
                f"/learners/{learner_payload['id']}/learning-goals/{goal_payload['id']}/progress"
            )
            assert progress_response.status_code == 200
            progress_payload = progress_response.json()
            assert progress_payload["target_count"] == 1
            assert progress_payload["covered_count"] == 1
            assert progress_payload["mastered_count"] == 1
            assert progress_payload["progress"] == 1.0
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
