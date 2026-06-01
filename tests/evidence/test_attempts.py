"""Tests for learner attempt submission."""

from __future__ import annotations

from typing import Any, cast

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from lms.evidence.api import create_attempt_route
from lms.evidence.repository import create_attempt, get_attempt, list_evidence_records
from lms.evidence.schemas import AttemptCreate, AttemptRead
from lms.scheduling.fsrs_adapter import evidence_to_fsrs_rating


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
    response_metadata = cast(dict[str, Any], attempt.response_metadata)
    assert response_metadata["answer_format"] == "text"
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


def test_post_attempt_with_scoring_creates_evidence_record(db_session: Session) -> None:
    """Posting attempt scoring metadata creates a linked evidence record."""
    payload = _attempt_payload()
    payload["evidence"] = {
        "knowledge_node_id": "node-1",
        "correctness": True,
        "raw_score": 2.0,
        "normalized_score": 1.0,
        "max_score": 2.0,
    }

    attempt_payload = AttemptCreate.model_validate(payload)
    created = create_attempt_route(attempt_payload, db_session)

    records = list_evidence_records(
        db_session,
        learner_id=attempt_payload.learner_id,
        knowledge_node_id="node-1",
    )
    assert len(records) == 1
    assert records[0].attempt_id == created.id
    assert records[0].correctness is True
    assert records[0].normalized_score == 1.0


def test_post_attempt_scoring_none_fields_fall_back_to_attempt_context(
    db_session: Session,
) -> None:
    """None values in dumped evidence payloads use attempt-level fallbacks."""
    payload = _attempt_payload()
    payload["evidence"] = {
        "knowledge_node_id": "node-1",
        "correctness": True,
        "response_time_seconds": None,
        "attempt_context": None,
    }

    attempt_payload = AttemptCreate.model_validate(payload)
    create_attempt_route(attempt_payload, db_session)

    records = list_evidence_records(
        db_session,
        learner_id=attempt_payload.learner_id,
        knowledge_node_id="node-1",
    )
    assert len(records) == 1
    assert records[0].response_time_seconds == attempt_payload.elapsed_seconds
    assert records[0].attempt_context == attempt_payload.response_metadata


def test_post_attempt_derives_normalized_score_from_raw_and_max_score(db_session: Session) -> None:
    """Raw/max scoring signals persist a normalized score for downstream schedulers."""
    payload = _attempt_payload()
    payload["evidence"] = {
        "knowledge_node_id": "node-1",
        "correctness": True,
        "raw_score": 3.0,
        "max_score": 4.0,
    }

    attempt_payload = AttemptCreate.model_validate(payload)
    create_attempt_route(attempt_payload, db_session)

    records = list_evidence_records(
        db_session,
        learner_id=attempt_payload.learner_id,
        knowledge_node_id="node-1",
    )
    assert len(records) == 1
    assert records[0].normalized_score == pytest.approx(0.75)


def test_post_attempt_with_zero_normalized_score_is_persisted_and_used(db_session: Session) -> None:
    """A zero score is explicit evidence and must not be treated as missing."""
    payload = _attempt_payload()
    payload["reference_accessed"] = False
    payload["support_level"] = "none"
    payload["evidence"] = {
        "knowledge_node_id": "node-1",
        "correctness": True,
        "normalized_score": 0.0,
    }

    attempt_payload = AttemptCreate.model_validate(payload)
    create_attempt_route(attempt_payload, db_session)

    records = list_evidence_records(
        db_session,
        learner_id=attempt_payload.learner_id,
        knowledge_node_id="node-1",
    )
    assert len(records) == 1
    assert records[0].normalized_score == 0.0
    rating = evidence_to_fsrs_rating(records[0])
    assert rating.rule_id == "partial-under-half"
    assert rating.label == "again"


def test_post_attempt_with_evidence_without_scoring_does_not_create_record(
    db_session: Session,
) -> None:
    """Evidence record is not created unless correctness or score fields are present."""
    payload = _attempt_payload()
    payload["evidence"] = {
        "knowledge_node_id": "node-1",
        "prompt_version_id": "prompt-version-1",
        "knowledge_type": "procedural",
    }

    attempt_payload = AttemptCreate.model_validate(payload)
    create_attempt_route(attempt_payload, db_session)

    records = list_evidence_records(
        db_session,
        learner_id=attempt_payload.learner_id,
        knowledge_node_id="node-1",
    )
    assert records == []
