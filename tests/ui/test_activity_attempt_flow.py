"""HTML contract tests for the learner activity attempt flow surface."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from lms.auth.models import utc_now
from lms.evidence.models import Attempt
from lms.evidence.repository import create_attempt
from lms.feedback.repository import create_rubric
from lms.feedback.scoring import score_attempt_with_rubric
from lms.graphs.models import KnowledgeNode
from lms.prompts.models import Prompt, PromptVersion
from lms.sources.models import SourceReference

ATTEMPTS_PATH = "/app/learner/attempts"
FEEDBACK_PATH = "/app/learner/attempts/feedback"


def test_attempt_flow_records_response_confidence_and_reference_access(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = api_client
    with session_factory() as session:
        _seed_prompt(session, visibility="public", locator="https://example.test/source")

    response = client.post(
        ATTEMPTS_PATH,
        data={
            "learner_id": "learner-1",
            "prompt_id": "prompt-1",
            "response_text": "Retrieval practice strengthens durable recall.",
            "confidence_rating": "4",
            "reference_accessed": "true",
            "elapsed_seconds": "42",
        },
    )

    assert response.status_code == 200
    html = response.text
    # The flow routes the learner to scored feedback after submitting.
    assert "<h1>Feedback</h1>" in html
    assert "Review feedback and continue practice." in html
    assert "Next review" in html

    with session_factory() as session:
        attempt = session.scalars(select(Attempt).where(Attempt.learner_id == "learner-1")).one()
    assert attempt.prompt_id == "prompt-1"
    assert attempt.response_text == "Retrieval practice strengthens durable recall."
    assert attempt.confidence_rating == 4
    assert attempt.reference_accessed is True
    assert attempt.elapsed_seconds == 42


def test_attempt_flow_routes_to_feedback_after_rubric_scoring(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = api_client
    with session_factory() as session:
        _seed_prompt(session, visibility="public", locator="https://example.test/source")
        rubric_id, criterion_id = _seed_rubric(session)

    submit = client.post(
        ATTEMPTS_PATH,
        data={
            "learner_id": "learner-1",
            "prompt_id": "prompt-1",
            "response_text": "A partial answer that misses the main idea.",
            "confidence_rating": "2",
        },
    )
    assert submit.status_code == 200

    # A downstream scorer scores the attempt below the feedback threshold,
    # which creates a remediation/revision feedback action.
    with session_factory() as session:
        attempt = session.scalars(select(Attempt).where(Attempt.learner_id == "learner-1")).one()
        score_attempt_with_rubric(
            session,
            rubric_id=rubric_id,
            attempt_id=attempt.id,
            scorer_type="rubric-self",
            criterion_scores=[{"criterion_id": criterion_id, "points": 1.0}],
        )
        session.commit()

    response = client.get(f"{FEEDBACK_PATH}?learner_id=learner-1&prompt_id=prompt-1")

    assert response.status_code == 200
    html = response.text
    assert "<h1>Feedback</h1>" in html
    assert "Rubric score" in html
    assert "1/4" in html
    assert "25%" in html
    assert "Revise the attempt using rubric feedback" in html
    assert "Next review" in html


def test_attempt_start_renders_prompt_metadata_provenance_and_citations(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = api_client
    with session_factory() as session:
        _seed_prompt(session, visibility="public", locator="https://example.test/source")

    response = client.get(f"{ATTEMPTS_PATH}?learner_id=learner-1&prompt_id=prompt-1")

    assert response.status_code == 200
    html = response.text
    assert "Explain the retrieval practice idea." in html
    assert "Demand level:" in html
    assert "Expected answer form:" in html
    assert 'name="confidence_rating"' in html
    assert 'name="reference_accessed"' in html
    assert "Provenance: human-authored; author author-1; reviewer reviewer-1." in html
    assert "Source citations after attempt" in html
    assert "https://example.test/source" in html


def test_attempt_start_hides_local_only_source_locator(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = api_client
    with session_factory() as session:
        _seed_prompt(
            session,
            visibility="local-only",
            locator="file:///Users/private/full-note-body.md",
        )

    response = client.get(f"{ATTEMPTS_PATH}?learner_id=learner-1&prompt_id=prompt-1")

    assert response.status_code == 200
    html = response.text
    assert "local-only source hidden" in html
    assert "file:///Users/private/full-note-body.md" not in html
    assert "hash-123" in html


def test_attempt_start_handles_missing_prompt(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _ = api_client

    no_prompt = client.get(f"{ATTEMPTS_PATH}?learner_id=learner-1")
    assert no_prompt.status_code == 200
    assert "No prompt selected" in no_prompt.text

    unknown = client.get(f"{ATTEMPTS_PATH}?learner_id=learner-1&prompt_id=missing")
    assert unknown.status_code == 200
    assert "No prompt selected" in unknown.text


def test_attempt_start_handles_unpublished_prompt(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = api_client
    with session_factory() as session:
        _seed_prompt(
            session,
            visibility="public",
            locator="https://example.test/source",
            status="draft",
        )

    response = client.get(f"{ATTEMPTS_PATH}?learner_id=learner-1&prompt_id=prompt-1")

    assert response.status_code == 200
    html = response.text
    assert "Prompt not available" in html
    assert "draft" in html
    assert 'name="response_text"' not in html


def test_attempt_start_flags_already_submitted_attempt(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = api_client
    with session_factory() as session:
        _seed_prompt(session, visibility="public", locator="https://example.test/source")

    first = client.post(
        ATTEMPTS_PATH,
        data={
            "learner_id": "learner-1",
            "prompt_id": "prompt-1",
            "response_text": "First attempt.",
            "confidence_rating": "3",
        },
    )
    assert first.status_code == 200

    response = client.get(f"{ATTEMPTS_PATH}?learner_id=learner-1&prompt_id=prompt-1")

    assert response.status_code == 200
    html = response.text
    assert "You already submitted an attempt for this prompt" in html
    assert f"{FEEDBACK_PATH}?learner_id=learner-1&prompt_id=prompt-1" in html


def test_attempt_start_url_encodes_feedback_link(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = api_client
    learner_id = "learner & one"
    prompt_id = "prompt&admin=true"
    with session_factory() as session:
        _seed_prompt(
            session,
            visibility="public",
            locator="https://example.test/source",
            prompt_id=prompt_id,
        )
        create_attempt(
            session,
            learner_id=learner_id,
            prompt_id=prompt_id,
            response_text="Previous response.",
            confidence_rating=3,
            feedback={"goal": "Record", "next_action": "Review feedback."},
        )
        session.commit()

    response = client.get(
        f"{ATTEMPTS_PATH}?learner_id=learner+%26+one&prompt_id=prompt%26admin%3Dtrue"
    )

    assert response.status_code == 200
    assert (
        f"{FEEDBACK_PATH}?learner_id=learner+%26+one&prompt_id=prompt%26admin%3Dtrue"
        in response.text
    )
    assert f"{FEEDBACK_PATH}?learner_id=learner &amp; one" not in response.text


def test_attempt_flow_rejects_empty_response_inline(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = api_client
    with session_factory() as session:
        _seed_prompt(session, visibility="public", locator="https://example.test/source")

    response = client.post(
        ATTEMPTS_PATH,
        data={
            "learner_id": "learner-1",
            "prompt_id": "prompt-1",
            "response_text": "",
            "confidence_rating": "3",
        },
    )

    assert response.status_code == 200
    assert "Enter a response" in response.text
    with session_factory() as session:
        attempts = session.scalars(select(Attempt)).all()
    assert attempts == []


def test_attempt_flow_rejects_invalid_numeric_fields_inline(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = api_client
    with session_factory() as session:
        _seed_prompt(session, visibility="public", locator="https://example.test/source")

    response = client.post(
        ATTEMPTS_PATH,
        data={
            "learner_id": "learner-1",
            "prompt_id": "prompt-1",
            "response_text": "A response with invalid numeric fields.",
            "confidence_rating": "not-a-number",
            "elapsed_seconds": "also-bad",
        },
    )

    assert response.status_code == 200
    assert "Enter a response" in response.text
    with session_factory() as session:
        attempts = session.scalars(select(Attempt)).all()
    assert attempts == []


def test_feedback_route_rejects_attempt_id_for_other_learner(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = api_client
    with session_factory() as session:
        _seed_prompt(session, visibility="public", locator="https://example.test/source")
        attempt = create_attempt(
            session,
            learner_id="learner-2",
            prompt_id="prompt-1",
            response_text="Other learner response.",
            confidence_rating=4,
            feedback={"goal": "Record", "next_action": "Review feedback."},
        )
        session.commit()
        attempt_id = attempt.id

    response = client.get(
        f"{FEEDBACK_PATH}?learner_id=learner-1&prompt_id=prompt-1&attempt_id={attempt_id}"
    )

    assert response.status_code == 200
    assert "No attempt yet" in response.text
    assert "Other learner response." not in response.text


def _seed_prompt(
    session: Session,
    *,
    visibility: str,
    locator: str,
    status: str = "published",
    prompt_id: str = "prompt-1",
) -> None:
    source = SourceReference(
        id="source-1",
        source_type="markdown-file",
        stable_locator=locator,
        passage_range="L1-L4",
        content_hash="hash-123",
        source_visibility=visibility,
        drift_status="current",
    )
    published = status == "published"
    prompt = Prompt(
        id=prompt_id,
        target_node_id="node-1",
        learning_goal_id="goal-1",
        knowledge_type="conceptual",
        intended_cognitive_action="explain",
        demand_level="medium",
        expected_answer_form="short-text",
        status=status,
        authoring_method="human-authored",
        authoring_actor="author-1",
        reviewing_actor="reviewer-1" if published else None,
        approval_timestamp=utc_now() if published else None,
        source_references=[source],
    )
    prompt.versions.append(
        PromptVersion(version_number=1, body="Explain the retrieval practice idea.", created_by="a")
    )
    session.add(prompt)
    session.commit()


def _seed_rubric(session: Session) -> tuple[str, str]:
    session.add(
        KnowledgeNode(
            id="node-1",
            title="Retrieval practice",
            knowledge_type="conceptual",
            ownership_scope="personal",
            status="published",
        )
    )
    session.flush()
    rubric = create_rubric(
        session,
        title="Explanation rubric",
        ownership_scope="personal",
        authoring_actor="author-1",
        prompt_id="prompt-1",
        status="published",
        criteria=[
            {
                "criterion_order": 1,
                "description": "States the main retrieval-practice idea",
                "max_points": 4.0,
            }
        ],
    )
    session.commit()
    return rubric.id, rubric.criteria[0].id
