"""HTML contract tests for the minimal Learn surface."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from lms.auth.models import utc_now
from lms.evidence.models import Attempt, EvidenceRecord
from lms.evidence.repository import create_attempt
from lms.evidence.service import RecordedAttempt, record_attempt
from lms.feedback.repository import create_feedback_action, create_feedback_record
from lms.prompts.models import Prompt, PromptVersion
from lms.sources.models import SourceReference
from lms.ui import api as learner_ui


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
    assert "Provenance: human-authored; author author-1; reviewer reviewer-1." in html
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
    html = response.text
    assert "Attempt recorded" in html
    assert "Confidence: <strong>4/5</strong>" in html
    assert 'action="/app/learner/attempts/self-grade"' in html
    assert "Source citations after attempt" in html
    assert "https://example.test/source" in html
    with session_factory() as session:
        attempts = session.scalars(select(Attempt).where(Attempt.learner_id == "learner-1")).all()
    assert len(attempts) == 1
    assert attempts[0].prompt_id == "prompt-1"
    assert attempts[0].confidence_rating == 4
    assert attempts[0].reference_accessed is True


@pytest.mark.parametrize("correctness", [None, True, False])
def test_learn_post_surfaces_self_grade_or_scored_correctness(
    api_client: tuple[TestClient, sessionmaker[Session]],
    monkeypatch: pytest.MonkeyPatch,
    correctness: bool | None,
) -> None:
    client, session_factory = api_client
    with session_factory() as session:
        _seed_prompt(session, visibility="public", locator="https://example.test/source")

    if correctness is not None:

        def record_with_scoring(session: Session, **kwargs: Any) -> RecordedAttempt:
            recorded = record_attempt(session, **kwargs)
            attempt = recorded.attempt
            session.add(
                EvidenceRecord(
                    attempt_id=attempt.id,
                    learner_id=attempt.learner_id,
                    knowledge_node_id="node-1",
                    correctness=correctness,
                )
            )
            feedback = create_feedback_record(
                session,
                learner_id=attempt.learner_id,
                attempt_id=attempt.id,
                goal="Explain retrieval <without notes>",
                observed_evidence="Used the definition but omitted an example.",
                gap="Give a concrete <example>",
            )
            create_feedback_action(
                session,
                learner_id=attempt.learner_id,
                attempt_id=attempt.id,
                feedback_record_id=feedback.id,
                action_type="retry",
                title="Try a concrete example",
                instructions="Compare <two examples> before retrying.",
            )
            return recorded

        monkeypatch.setattr(learner_ui, "record_attempt", record_with_scoring)

    response = client.post(
        "/learn/attempts",
        data={
            "learner_id": "learner-1",
            "prompt_id": "prompt-1",
            "response_text": "Retrieval practice strengthens recall.",
            "confidence_rating": "4",
        },
    )
    assert response.status_code == 200
    html = response.text
    assert "Correctness: pending scoring evidence." not in html
    if correctness is None:
        assert 'action="/app/learner/attempts/self-grade"' in html
        assert 'name="grade" value="correct"' in html
        assert 'name="grade" value="incorrect"' in html
    else:
        label = "correct" if correctness else "incorrect"
        assert f"Correctness: {label}." in html
        assert "Explain retrieval &lt;without notes&gt;" in html
        assert "Gap: Give a concrete &lt;example&gt;" in html
        assert "Try a concrete example" in html
        assert "Compare &lt;two examples&gt; before retrying." in html
        assert 'class="self-grade"' not in html


def test_learn_surface_shows_confidence_against_scoring_evidence(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = api_client
    with session_factory() as session:
        _seed_prompt(session, visibility="public", locator="https://example.test/source")
        create_attempt(
            session,
            learner_id="learner-1",
            prompt_id="prompt-1",
            response_text="Retrieval practice strengthens recall.",
            confidence_rating=5,
            reference_accessed=False,
            feedback={
                "goal": "Record learner attempt",
                "observed_evidence": "Retrieval practice strengthens recall.",
                "next_action": "Continue.",
            },
            evidence={
                "knowledge_node_id": "node-1",
                "correctness": True,
                "normalized_score": 1.0,
            },
        )
        session.commit()

    response = client.get("/learn?learner_id=learner-1&prompt_id=prompt-1")

    assert response.status_code == 200
    assert "Latest evidence: confidence 5/5; correctness correct." in response.text


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
