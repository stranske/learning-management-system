"""Tests for persisted LLM learning interaction skills."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from lms.llm.models import LearningInteractionSkill


def test_create_interaction_skill_for_transfer_mode(db_session: Session) -> None:
    """A named transfer-mode interaction skill persists policy and trace constraints."""
    skill = LearningInteractionSkill(
        name="transfer-feedback-synthesis",
        mode="transfer",
        policy_version="segment-10-v1",
        description="Summarize transfer evidence without leaking source text.",
        allowed_trace_classes=["formative", "evidence-grade"],
        source_citation_required=True,
    )
    db_session.add(skill)
    db_session.commit()

    fetched = db_session.get(LearningInteractionSkill, skill.id)

    assert fetched is not None
    assert fetched.mode == "transfer"
    assert fetched.policy_version == "segment-10-v1"
    assert fetched.allowed_trace_classes == ["formative", "evidence-grade"]
    assert fetched.source_citation_required is True
    assert fetched.active is True


def test_create_duplicate_interaction_skill_returns_409(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    """Re-posting the same (name, policy_version) returns 409 instead of a 500."""
    client, _session_factory = api_client
    payload = {
        "name": "retrieval-nudge",
        "mode": "study-coach",
        "policy_version": "study-coach-policy-v1",
        "description": "Prompt learners to use cited retrieval before direct answers.",
    }

    first = client.post("/llm/interaction-skills", json=payload)
    assert first.status_code == 201

    duplicate = client.post("/llm/interaction-skills", json=payload)
    assert duplicate.status_code == 409


def test_create_session_with_mismatched_skill_mode_returns_422(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    """A session linked to a skill registered for a different mode is rejected."""
    client, _session_factory = api_client
    skill = client.post(
        "/llm/interaction-skills",
        json={
            "name": "practice-only-skill",
            "mode": "practice",
            "policy_version": "v1",
            "description": "Practice-mode skill.",
            "allowed_trace_classes": ["evidence-grade", "formative", "ephemeral"],
        },
    )
    assert skill.status_code == 201
    skill_id = skill.json()["id"]

    response = client.post(
        "/llm/sessions",
        json={
            "learner_id": "learner-1",
            "mode": "study-coach",
            "user_message": "Tell me the answer",
            "retrieval_active": True,
            "skill_id": skill_id,
        },
    )

    assert response.status_code == 422


def test_create_session_with_matching_active_skill_succeeds(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    """A session linked to an active, mode-matched, trace-permitted skill persists."""
    client, _session_factory = api_client
    skill = client.post(
        "/llm/interaction-skills",
        json={
            "name": "study-coach-skill",
            "mode": "study-coach",
            "policy_version": "v1",
            "description": "Study-coach skill.",
            "allowed_trace_classes": ["evidence-grade", "formative", "ephemeral"],
        },
    )
    assert skill.status_code == 201
    skill_id = skill.json()["id"]

    response = client.post(
        "/llm/sessions",
        json={
            "learner_id": "learner-1",
            "mode": "study-coach",
            "user_message": "Tell me the answer",
            "retrieval_active": True,
            "skill_id": skill_id,
        },
    )

    assert response.status_code == 200
