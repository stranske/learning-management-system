"""Tests for LLM per-turn feedback event persistence."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from lms.llm.models import LearningInteractionSkill, LLMFeedbackEvent, LLMSession


def _llm_session(db_session: Session, *, trace_class: str = "formative") -> LLMSession:
    session = LLMSession(
        mode="study-coach",
        trace_class=trace_class,
        provider="fake",
        model="fake-learning-policy",
        learner_id="learner-1",
        cost_micro_usd=12,
    )
    db_session.add(session)
    db_session.flush()
    return session


def test_llm_feedback_event_records_trace_class_and_citations(db_session: Session) -> None:
    """Feedback events preserve trace class, source references, and cost metadata."""
    llm_session = _llm_session(db_session, trace_class="evidence-grade")
    skill = LearningInteractionSkill(
        name="retrieval-nudge",
        mode="study-coach",
        policy_version="study-coach-policy-v1",
        description="Prompt learners to use cited retrieval before direct answers.",
        allowed_trace_classes=["evidence-grade", "formative"],
    )
    db_session.add(skill)
    db_session.flush()

    event = LLMFeedbackEvent(
        llm_session_id=llm_session.id,
        learner_id="learner-1",
        skill_id=skill.id,
        event_type="source-citation-check",
        trace_class="evidence-grade",
        source_reference_ids=["source-1", "source-2"],
        unverified=True,
        cost_metadata={"cost_micro_usd": 12, "input_tokens": 4, "output_tokens": 8},
        event_summary="retrieval required before direct answer",
        event_body="Use the linked source before answering.",
    )
    db_session.add(event)
    db_session.commit()

    fetched = db_session.get(LLMFeedbackEvent, event.id)

    assert fetched is not None
    assert fetched.trace_class == "evidence-grade"
    assert fetched.source_reference_ids == ["source-1", "source-2"]
    assert fetched.cost_metadata["cost_micro_usd"] == 12
    assert fetched.unverified is True
    assert fetched.skill_id == skill.id


def test_ephemeral_feedback_event_excludes_verbatim_body_by_default(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    """The API records ephemeral feedback metadata without retaining the verbatim body."""
    client, _session_factory = api_client
    session_response = client.post(
        "/llm/sessions",
        json={
            "learner_id": "learner-1",
            "mode": "study-coach",
            "user_message": "I think this is true without a source.",
            "source_constraints": ["source-1"],
            "retrieval_active": False,
        },
    )
    assert session_response.status_code == 200
    llm_session_id = session_response.json()["session_id"]

    response = client.post(
        "/llm/feedback-events",
        json={
            "llm_session_id": llm_session_id,
            "learner_id": "learner-1",
            "event_type": "manual-review",
            "trace_class": "ephemeral",
            "event_summary": "learner asked for a transient hint",
            "event_body": "verbatim learner text should not be retained",
            "cost_metadata": {"cost_micro_usd": 12},
        },
    )

    assert response.status_code == 201
    body: dict[str, Any] = response.json()
    assert body["trace_class"] == "ephemeral"
    assert body["body_retained"] is False


def _create_study_coach_session(client: TestClient, *, learner_id: str = "learner-1") -> str:
    response = client.post(
        "/llm/sessions",
        json={
            "learner_id": learner_id,
            "mode": "study-coach",
            "user_message": "Explain spaced practice.",
            "retrieval_active": False,
        },
    )
    assert response.status_code == 200
    return response.json()["session_id"]


def test_feedback_event_learner_mismatch_returns_422(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    """A feedback event whose learner differs from the linked session learner is rejected."""
    client, _session_factory = api_client
    llm_session_id = _create_study_coach_session(client, learner_id="learner-1")

    response = client.post(
        "/llm/feedback-events",
        json={
            "llm_session_id": llm_session_id,
            "learner_id": "learner-2",
            "event_type": "manual-review",
            "trace_class": "formative",
        },
    )

    assert response.status_code == 422


def test_feedback_event_trace_class_outside_skill_allowed_returns_422(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    """A feedback event trace class outside the linked skill's allowed set is rejected."""
    client, _session_factory = api_client
    llm_session_id = _create_study_coach_session(client)
    skill_response = client.post(
        "/llm/interaction-skills",
        json={
            "name": "evidence-only-skill",
            "mode": "study-coach",
            "policy_version": "v1",
            "description": "Only evidence-grade traces permitted.",
            "allowed_trace_classes": ["evidence-grade"],
        },
    )
    assert skill_response.status_code == 201
    skill_id = skill_response.json()["id"]

    response = client.post(
        "/llm/feedback-events",
        json={
            "llm_session_id": llm_session_id,
            "learner_id": "learner-1",
            "skill_id": skill_id,
            "event_type": "manual-review",
            "trace_class": "formative",
        },
    )

    assert response.status_code == 422


def test_feedback_event_inactive_skill_returns_422(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    """A feedback event linked to an inactive skill is rejected."""
    client, _session_factory = api_client
    llm_session_id = _create_study_coach_session(client)
    skill_response = client.post(
        "/llm/interaction-skills",
        json={
            "name": "inactive-skill",
            "mode": "study-coach",
            "policy_version": "v1",
            "description": "Inactive skill.",
            "allowed_trace_classes": ["evidence-grade", "formative", "ephemeral"],
            "active": False,
        },
    )
    assert skill_response.status_code == 201
    skill_id = skill_response.json()["id"]

    response = client.post(
        "/llm/feedback-events",
        json={
            "llm_session_id": llm_session_id,
            "learner_id": "learner-1",
            "skill_id": skill_id,
            "event_type": "manual-review",
            "trace_class": "formative",
        },
    )

    assert response.status_code == 422
