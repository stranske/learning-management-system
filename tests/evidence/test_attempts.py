"""Tests for learner attempt submission."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from lms.evidence.api import create_attempt_route
from lms.evidence.repository import create_attempt, get_attempt
from lms.evidence.schemas import AttemptCreate, AttemptRead


def _attempt_payload() -> dict[str, object]:
    return {
        "learner_id": "learner-1",
        "prompt_id": "prompt-1",
        "response_text": "I used inverse operations to isolate x.",
        "response_metadata": {"answer_format": "text", "client_version": "web-1"},
        "confidence_rating": 4,
        "reference_accessed": True,
        "hint_used": False,
        "support_level": "reference",
        "elapsed_seconds": 42,
        "feedback": {
            "goal": "Solve one-step equations",
            "observed_evidence": "Explained inverse operation choice.",
            "gap": "Needs a numeric example.",
            "next_action": "Practice two one-step equations.",
        },
    }


def test_submit_attempt_with_confidence_and_reference_use(db_session: Session) -> None:
    """Attempt save returns stable id with confidence and reference tracking."""
    payload = AttemptCreate.model_validate(_attempt_payload())

    attempt = create_attempt(db_session, **payload.model_dump())
    db_session.commit()

    assert attempt.id
    assert attempt.learner_id == "learner-1"
    assert attempt.prompt_id == "prompt-1"
    assert attempt.response_metadata["answer_format"] == "text"
    assert attempt.confidence_rating == 4
    assert attempt.reference_accessed is True
    assert attempt.support_level == "reference"


def test_structured_feedback_requires_next_action(db_session: Session) -> None:
    """Attempt feedback must include an actionable learner next step."""
    payload = _attempt_payload()
    payload["feedback"] = {
        "goal": "Solve one-step equations",
        "observed_evidence": "Explained inverse operation choice.",
        "gap": "Needs a numeric example.",
    }

    with pytest.raises(ValidationError):
        AttemptCreate.model_validate(payload)


def test_attempt_confidence_validation() -> None:
    """Confidence is bounded to the v1 five-point learner rating scale."""
    payload = _attempt_payload()
    payload["confidence_rating"] = 6

    with pytest.raises(ValidationError):
        AttemptCreate.model_validate(payload)


def test_get_attempt_returns_recorded_feedback(db_session: Session) -> None:
    """Readback by id returns the stored structured feedback."""
    payload = AttemptCreate.model_validate(_attempt_payload())
    created = create_attempt(db_session, **payload.model_dump())
    db_session.commit()

    loaded = get_attempt(db_session, created.id)

    assert loaded is not None
    assert loaded.feedback["next_action"] == "Practice two one-step equations."


def test_post_attempt_route_returns_stable_linked_attempt_id(db_session: Session) -> None:
    """POST route handler returns id linked to learner and prompt ids."""
    payload = AttemptCreate.model_validate(_attempt_payload())

    created = create_attempt_route(payload, db_session)

    assert isinstance(created, AttemptRead)
    assert created.id
    assert created.learner_id == payload.learner_id
    assert created.prompt_id == payload.prompt_id

    loaded = get_attempt(db_session, created.id)
    assert loaded is not None
    assert loaded.learner_id == payload.learner_id
    assert loaded.prompt_id == payload.prompt_id
