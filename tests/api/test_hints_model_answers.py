"""Tests for hint and model-answer API routes."""

from __future__ import annotations

from typing import Any, cast

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from lms.db.session import get_session
from lms.evidence.repository import create_attempt
from lms.main import create_app
from lms.prompts.models import Prompt, PromptVersion
from lms.sources.repository import create_source_reference


def _client(db_session: Session) -> TestClient:
    app = create_app(enable_local_identity_routes=True)
    app.dependency_overrides[get_session] = lambda: db_session
    return TestClient(app)


def _prompt(db_session: Session) -> Prompt:
    public_ref = create_source_reference(
        db_session,
        source_type="url",
        stable_locator="https://example.test/fractions",
        content="Fraction source",
        actor_id="user:alice",
        source_visibility="public",
    )
    local_ref = create_source_reference(
        db_session,
        source_type="markdown-file",
        stable_locator="/Users/teacher/private/fractions.md",
        content="Local source",
        actor_id="user:alice",
        source_visibility="local-only",
    )
    prompt = Prompt(
        target_node_id="node-1",
        learning_goal_id="goal-1",
        knowledge_type="conceptual",
        intended_cognitive_action="explain",
        demand_level="medium",
        expected_answer_form="short-text",
        status="draft",
        authoring_method="human-authored",
        authoring_actor="user:alice",
        source_references=[public_ref, local_ref],
    )
    prompt.versions.append(
        PromptVersion(
            version_number=1, body="Explain equivalent fractions.", created_by="user:alice"
        )
    )
    db_session.add(prompt)
    db_session.flush()
    return prompt


def test_hints_api_lists_without_model_answer_content_and_reveal_marks_support(
    db_session: Session,
) -> None:
    """Hint routes expose ordered hints and record support use."""
    prompt = _prompt(db_session)
    attempt = create_attempt(
        db_session,
        learner_id="learner-1",
        prompt_id=prompt.id,
        response_text="I only changed the numerator.",
        feedback={"goal": "Equivalent fractions"},
        evidence={
            "knowledge_node_id": "node-1",
            "correctness": False,
            "normalized_score": 0.25,
            "max_score": 1,
        },
    )
    client = _client(db_session)

    answer_response = client.post(
        "/model-answers",
        json={
            "prompt_id": prompt.id,
            "answer_body": "Use the same multiplier for both terms.",
            "authoring_actor": "user:alice",
        },
    )
    assert answer_response.status_code == 201, answer_response.text
    hint_response = client.post(
        "/hints",
        json={
            "prompt_id": prompt.id,
            "hint_text": "Use the same multiplier for both terms.",
            "reveal_order": 1,
            "authoring_actor": "user:alice",
        },
    )
    assert hint_response.status_code == 201, hint_response.text
    hint = cast(dict[str, Any], hint_response.json())

    list_response = client.get("/hints", params={"prompt_id": prompt.id})
    assert list_response.status_code == 200
    listed = list_response.json()
    assert listed[0]["hint_text"] == "Use the same multiplier for both terms."
    assert "answer_body" not in listed[0]
    assert not any(
        citation["stable_locator"] == "/Users/teacher/private/fractions.md"
        for citation in listed[0]["source_citations"]
    )

    reveal_response = client.post(
        f"/hints/{hint['id']}/reveal",
        json={"learner_id": "learner-1", "attempt_id": attempt.id},
    )
    assert reveal_response.status_code == 200, reveal_response.text
    db_session.refresh(attempt)
    assert attempt.hint_used is True
    assert attempt.evidence_records[0].hint_used is True


def test_model_answer_api_requires_attempt_before_reveal(db_session: Session) -> None:
    """Model answer bodies stay hidden until learner attempt or instructor mode."""
    prompt = _prompt(db_session)
    client = _client(db_session)
    create_response = client.post(
        "/model-answers",
        json={
            "prompt_id": prompt.id,
            "answer_body": "Use the same multiplier for numerator and denominator.",
            "authoring_actor": "user:alice",
        },
    )
    assert create_response.status_code == 201, create_response.text
    answer = create_response.json()

    list_response = client.get("/model-answers", params={"prompt_id": prompt.id})
    assert list_response.status_code == 200
    assert "answer_body" not in list_response.json()[0]

    blocked_response = client.post(
        f"/model-answers/{answer['id']}/reveal",
        json={"learner_id": "learner-1"},
    )
    assert blocked_response.status_code == 422
    assert "requires a completed attempt" in blocked_response.json()["detail"]

    attempt = create_attempt(
        db_session,
        learner_id="learner-1",
        prompt_id=prompt.id,
        response_text="I attempted before reveal.",
        feedback={"goal": "Equivalent fractions"},
    )
    reveal_response = client.post(
        f"/model-answers/{answer['id']}/reveal",
        json={"learner_id": "learner-1", "attempt_id": attempt.id},
    )
    assert reveal_response.status_code == 200, reveal_response.text
    assert "same multiplier" in reveal_response.json()["answer_body"]
