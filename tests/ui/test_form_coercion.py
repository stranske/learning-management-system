"""Route-level and helper tests for shared UI numeric form coercion."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from lms.evidence.models import Attempt
from lms.ui.forms import FormValueError, optional_int

ATTEMPTS_PATH = "/app/learner/attempts"


def test_non_numeric_confidence_does_not_500(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = api_client
    with session_factory() as session:
        _seed_prompt(session)

    response = client.post(
        ATTEMPTS_PATH,
        data={
            "learner_id": "learner-1",
            "prompt_id": "prompt-1",
            "response_text": "A response with invalid confidence.",
            "confidence_rating": "abc",
        },
    )

    assert response.status_code < 500
    assert "validation-error" in response.text
    with session_factory() as session:
        assert session.scalars(select(Attempt)).all() == []


def test_blank_numeric_field_is_treated_as_absent(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = api_client
    with session_factory() as session:
        _seed_prompt(session)

    response = client.post(
        ATTEMPTS_PATH,
        data={
            "learner_id": "learner-1",
            "prompt_id": "prompt-1",
            "response_text": "A response without confidence.",
            "confidence_rating": "",
        },
    )

    assert response.status_code == 200
    with session_factory() as session:
        attempt = session.scalars(select(Attempt).where(Attempt.learner_id == "learner-1")).one()
    assert attempt.confidence_rating is None


def test_optional_int_rejects_non_numeric() -> None:
    with pytest.raises(FormValueError):
        optional_int("abc")
    assert optional_int("") is None
    assert optional_int(None) is None


def _seed_prompt(session: Session) -> None:
    from lms.auth.models import utc_now
    from lms.graphs.models import KnowledgeNode
    from lms.prompts.models import Prompt, PromptVersion
    from lms.sources.models import SourceReference

    source = SourceReference(
        id="source-1",
        source_type="markdown-file",
        stable_locator="https://example.test/source",
        passage_range="L1-L4",
        content_hash="hash-123",
        source_visibility="public",
        drift_status="current",
    )
    prompt = Prompt(
        id="prompt-1",
        target_node_id="node-1",
        learning_goal_id="goal-1",
        knowledge_type="conceptual",
        intended_cognitive_action="explain",
        demand_level="medium",
        expected_answer_form="short-text",
        status="published",
        authoring_method="human-authored",
        authoring_actor="author-1",
        reviewing_actor="reviewer-1",
        approval_timestamp=utc_now(),
        source_references=[source],
    )
    prompt.versions.append(
        PromptVersion(version_number=1, body="Explain the retrieval practice idea.", created_by="a")
    )
    session.add(
        KnowledgeNode(
            id="node-1",
            title="Retrieval practice",
            knowledge_type="conceptual",
            ownership_scope="personal",
            status="published",
        )
    )
    session.add(prompt)
    session.commit()
