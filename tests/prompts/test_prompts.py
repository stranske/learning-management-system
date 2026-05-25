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
    assert response.json()["detail"][0]["loc"] == ["body", "source_reference_ids"]


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
    assert audit.after_summary is not None
    assert audit.after_summary["approval_timestamp"].startswith(body["approval_timestamp"])


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


def test_get_and_list_prompts_include_source_ids_and_versions(
    api_client: tuple[TestClient, Session],
) -> None:
    """GET /prompts and GET /prompts/{id} expose provenance and version metadata."""
    client, session = api_client
    ids = _seed_prompt_dependencies(session)
    created = client.post("/prompts", json=_prompt_payload(ids))
    assert created.status_code == 201, created.text
    prompt_id = cast(str, created.json()["id"])

    listed = client.get("/prompts")
    assert listed.status_code == 200, listed.text
    listed_payload = listed.json()
    assert len(listed_payload) == 1
    assert listed_payload[0]["id"] == prompt_id
    assert listed_payload[0]["source_reference_ids"] == [ids["source_id"]]
    assert listed_payload[0]["versions"][0]["version_number"] == 1

    fetched = client.get(f"/prompts/{prompt_id}")
    assert fetched.status_code == 200, fetched.text
    fetched_payload = fetched.json()
    assert fetched_payload["id"] == prompt_id
    assert fetched_payload["source_reference_ids"] == [ids["source_id"]]
    assert fetched_payload["versions"][0]["body"].startswith("Explain why retrieval practice")


def test_version_prompt_appends_version_metadata(
    api_client: tuple[TestClient, Session],
) -> None:
    """POST /prompts/{id}/versions appends immutable version metadata."""
    client, session = api_client
    ids = _seed_prompt_dependencies(session)
    created = client.post("/prompts", json=_prompt_payload(ids))
    assert created.status_code == 201, created.text
    prompt_id = cast(str, created.json()["id"])

    versioned = client.post(
        f"/prompts/{prompt_id}/versions",
        json={
            "body": "Apply retrieval practice to this week of notes.",
            "actor_id": "user:alice",
            "demand_level": "high",
        },
    )
    assert versioned.status_code == 200, versioned.text
    payload = versioned.json()
    assert payload["demand_level"] == "high"
    assert len(payload["versions"]) == 2
    assert payload["versions"][1]["version_number"] == 2
    assert payload["versions"][1]["created_by"] == "user:alice"


def test_version_prompt_rejects_direct_published_status(
    api_client: tuple[TestClient, Session],
) -> None:
    """Prompt version updates cannot bypass the dedicated publish flow."""
    client, session = api_client
    ids = _seed_prompt_dependencies(session)
    created = client.post("/prompts", json=_prompt_payload(ids))
    assert created.status_code == 201, created.text
    prompt_id = cast(str, created.json()["id"])

    from lms.prompts.repository import get_prompt, version_prompt

    prompt = get_prompt(session, prompt_id)
    assert prompt is not None

    with pytest.raises(ValueError, match="use publish_prompt"):
        version_prompt(
            session,
            prompt,
            body="Try to publish through a version update.",
            actor_id="user:alice",
            status="published",
        )
