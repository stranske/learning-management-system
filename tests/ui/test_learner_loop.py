"""HTML contract tests for the minimal Learn surface."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from lms.auth.models import utc_now
from lms.evidence.models import Attempt
from lms.prompts.models import Prompt, PromptVersion
from lms.sources.models import SourceReference


def test_submit_prompt_attempt_with_confidence(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = api_client
    with session_factory() as session:
        _seed_prompt(session, visibility="public", locator="https://example.test/source")

    response = client.get("/learn?learner_id=learner-1&prompt_id=prompt-1")

    assert response.status_code == 200
    html = response.text
    assert 'name="confidence_rating"' in html
    assert 'name="reference_accessed"' in html
    assert 'action="/learn/attempts"' in html
    assert "Explain the retrieval practice idea." in html
    assert "Source citations after attempt" in html
    assert "https://example.test/source" in html
    assert 'name="viewport"' in html


def test_learn_surface_form_records_attempt(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = api_client
    with session_factory() as session:
        _seed_prompt(session, visibility="public", locator="https://example.test/source")

    response = client.post(
        "/learn/attempts",
        data={
            "learner_id": "learner-1",
            "prompt_id": "prompt-1",
            "response_text": "Retrieval practice strengthens recall.",
            "confidence_rating": "4",
            "reference_accessed": "true",
        },
    )

    assert response.status_code == 200
    assert "Attempt recorded" in response.text
    with session_factory() as session:
        attempts = session.scalars(select(Attempt).where(Attempt.learner_id == "learner-1")).all()
    assert len(attempts) == 1
    assert attempts[0].prompt_id == "prompt-1"
    assert attempts[0].confidence_rating == 4
    assert attempts[0].reference_accessed is True


def test_learn_surface_hides_local_only_source_locator(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = api_client
    with session_factory() as session:
        _seed_prompt(
            session,
            visibility="local-only",
            locator="file:///Users/private/full-note-body.md",
        )

    response = client.get("/learn?learner_id=learner-1&prompt_id=prompt-1")

    assert response.status_code == 200
    html = response.text
    assert "local-only source hidden" in html
    assert "file:///Users/private/full-note-body.md" not in html
    assert "hash-123" in html


def _seed_prompt(session: Session, *, visibility: str, locator: str) -> None:
    source = SourceReference(
        id="source-1",
        source_type="markdown-file",
        stable_locator=locator,
        passage_range="L1-L4",
        content_hash="hash-123",
        source_visibility=visibility,
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
    session.add(prompt)
    session.commit()
