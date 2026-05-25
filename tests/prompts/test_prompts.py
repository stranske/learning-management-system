"""API tests for prompt provenance and publication."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from lms.audit.models import AuditLog
from lms.db.base import Base
from lms.db.session import get_session
from lms.graphs.repository import create_knowledge_node
from lms.learners.repository import create_learner_for_user, create_learning_goal
from lms.main import create_app
from lms.sources.repository import create_source_reference


@pytest.fixture
def api_client() -> Generator[tuple[TestClient, Session], None, None]:
    """Provide a FastAPI test client backed by a shared in-memory SQLite engine."""
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    setup_session = session_factory()

    def override_get_session() -> Generator[Session, None, None]:
        request_session = session_factory()
        try:
            yield request_session
        finally:
            request_session.close()

    app = create_app()
    app.dependency_overrides[get_session] = override_get_session
    try:
        with TestClient(app) as client:
            yield client, setup_session
    finally:
        setup_session.close()
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def _seed_prompt_dependencies(session: Session) -> dict[str, str]:
    node = create_knowledge_node(
        session,
        title="Retrieval practice",
        knowledge_type="conceptual",
        scope="personal",
        status="published",
        actor_id="user:alice",
    )
    learner = create_learner_for_user(
        session,
        user_id="user-alice",
        display_name="Alice",
    )
    goal = create_learning_goal(
        session,
        learner_id=learner.id,
        title="Learn retrieval practice",
        knowledge_type="conceptual",
        target_node_ids=[node.id],
        ownership_scope="personal",
    )
    source = create_source_reference(
        session,
        source_type="url",
        stable_locator="https://example.test/retrieval",
        content="retrieval practice improves durable recall",
        actor_id="user:alice",
    )
    session.commit()
    return {"node_id": node.id, "goal_id": goal.id, "source_id": source.id}


def _prompt_payload(ids: dict[str, str], **overrides: Any) -> dict[str, Any]:
    payload = {
        "target_node_id": ids["node_id"],
        "learning_goal_id": ids["goal_id"],
        "knowledge_type": "conceptual",
        "intended_cognitive_action": "explain",
        "demand_level": "medium",
        "expected_answer_form": "short-text",
        "body": "Explain why retrieval practice improves long-term recall.",
        "source_reference_ids": [ids["source_id"]],
        "authoring_method": "human-authored",
        "authoring_actor": "user:alice",
        "prompt_template_version": "retrieval-v1",
    }
    payload.update(overrides)
    return payload


def test_prompt_requires_source_reference(
    api_client: tuple[TestClient, Session],
) -> None:
    """POST /prompts rejects prompts without source citations."""
    client, session = api_client
    ids = _seed_prompt_dependencies(session)
    payload = _prompt_payload(ids, source_reference_ids=[])

    response = client.post("/prompts", json=payload)

    assert response.status_code == 422
    assert "source reference" in response.text


def test_llm_generated_prompt_starts_draft(
    api_client: tuple[TestClient, Session],
) -> None:
    """LLM-authored prompts cannot be born published before human review."""
    client, session = api_client
    ids = _seed_prompt_dependencies(session)
    payload = _prompt_payload(
        ids,
        authoring_method="llm-generated",
        llm_model="gpt-5.4",
        status="in-review",
    )

    response = client.post("/prompts", json=payload)

    assert response.status_code == 422
    assert "llm-generated prompts must start as draft" in response.text

    payload["status"] = "draft"
    created = client.post("/prompts", json=payload)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["status"] == "draft"
    assert body["authoring_method"] == "llm-generated"
    assert body["llm_model"] == "gpt-5.4"


def test_publish_prompt_records_reviewing_actor_and_approval_timestamp(
    api_client: tuple[TestClient, Session],
) -> None:
    """POST /prompts/{id}/publish stores review provenance and audit evidence."""
    client, session = api_client
    ids = _seed_prompt_dependencies(session)
    created = client.post("/prompts", json=_prompt_payload(ids))
    assert created.status_code == 201, created.text
    prompt_id = cast(str, created.json()["id"])

    response = client.post(
        f"/prompts/{prompt_id}/publish",
        json={"reviewing_actor": "reviewer:bob"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "published"
    assert body["reviewing_actor"] == "reviewer:bob"
    assert body["approval_timestamp"] is not None

    audit = (
        session.query(AuditLog)
        .filter_by(entity_type="Prompt", entity_id=prompt_id, action="publish")
        .one()
    )
    assert audit.actor_id == "reviewer:bob"


def test_post_prompts_returns_source_reference_ids_and_provenance(
    api_client: tuple[TestClient, Session],
) -> None:
    """POST /prompts returns linked SourceReference ids and provenance fields."""
    client, session = api_client
    ids = _seed_prompt_dependencies(session)

    response = client.post("/prompts", json=_prompt_payload(ids))

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["source_reference_ids"] == [ids["source_id"]]
    assert body["authoring_actor"] == "user:alice"
    assert body["prompt_template_version"] == "retrieval-v1"
    assert body["versions"][0]["version_number"] == 1
