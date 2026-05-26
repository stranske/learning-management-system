"""Tests for durable feedback records promoted from attempts."""

from __future__ import annotations

from sqlalchemy.orm import Session

from lms.evidence.repository import create_attempt
from lms.evidence.schemas import AttemptCreate
from lms.feedback.repository import list_feedback_actions, list_feedback_records


def _attempt_payload() -> dict[str, object]:
    return {
        "learner_id": "learner-1",
        "prompt_id": "prompt-1",
        "response_text": "I solved the first equation but skipped the check.",
        "confidence_rating": 3,
        "feedback": {
            "goal": "Solve equations and verify the solution.",
            "observed_evidence": "Isolated x correctly.",
            "gap": "Needs to substitute the solution back into the equation.",
            "next_action": "Retry with a required substitution check.",
        },
    }


def test_attempt_feedback_promotes_to_feedback_record(db_session: Session) -> None:
    """Attempt creation promotes legacy feedback into durable feedback rows."""
    payload = AttemptCreate.model_validate(_attempt_payload())

    attempt = create_attempt(db_session, **payload.model_dump())
    db_session.commit()

    records = list_feedback_records(
        db_session,
        learner_id=payload.learner_id,
        attempt_id=attempt.id,
        feedback_level="remediation",
    )
    assert len(records) == 1
    assert records[0].prompt_id == payload.prompt_id
    assert records[0].gap == "Needs to substitute the solution back into the equation."
    assert records[0].source_feedback["next_action"] == "Retry with a required substitution check."

    actions = list_feedback_actions(
        db_session,
        learner_id=payload.learner_id,
        feedback_record_id=records[0].id,
        status="open",
    )
    assert len(actions) == 1
    assert actions[0].action_type == "prerequisite-remediation"
    assert actions[0].title == "Retry with a required substitution check."
    assert records[0].next_action_ids == [actions[0].id]
