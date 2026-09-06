"""Rubric scoring must commit evidence and scheduling together or neither."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

import lms.feedback.scoring as scoring_module
from lms.evidence.models import Attempt, EvidenceRecord
from lms.evidence.repository import create_attempt
from lms.evidence.service import schedule_for_evidence
from lms.feedback.models import FeedbackAction, FeedbackRecord, RubricScore
from lms.feedback.repository import create_rubric
from lms.scheduling.models import ReviewQueueItem, ReviewSchedule, SchedulerDecision
from tests.scheduling.test_attempt_to_next_review_e2e import (
    _seed_learner_node_prompt,
    loop_client,  # noqa: F401 -- reuse the isolated production API fixture
)


@pytest.mark.parametrize("failure_point", ["before-scheduling", "after-scheduling"])
def test_rubric_score_does_not_commit_when_post_evidence_scheduling_fails(
    loop_client: tuple[TestClient, sessionmaker[Session]],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    failure_point: str,
) -> None:
    """A failed HTTP score leaves no partial rows and can be retried safely."""
    client, session_factory = loop_client
    learner_id, node_id, prompt_id = _seed_learner_node_prompt(session_factory)
    with session_factory() as session:
        rubric = create_rubric(
            session,
            title="Atomic scoring",
            ownership_scope="personal",
            authoring_actor="system:e2e-loop-test",
            knowledge_node_id=node_id,
            criteria=[{"criterion_order": 1, "description": "Correct reasoning.", "max_points": 5}],
        )
        attempt = create_attempt(
            session,
            learner_id=learner_id,
            prompt_id=prompt_id,
            response_text="An incorrect explanation.",
            confidence_rating=5,
            feedback={"goal": "Practice reasoning."},
        )
        session.commit()
        attempt_id = attempt.id
        payload = {
            "rubric_id": rubric.id,
            "attempt_id": attempt_id,
            "scorer_type": "human",
            "criterion_scores": [{"criterion_id": rubric.criteria[0].id, "points": 1}],
        }
        # Creating the original attempt already writes feedback; preserve it
        # while checking that the failed scoring transaction adds nothing.
        baseline_ids = {
            model: set(session.scalars(select(model.id)))
            for model in (
                RubricScore,
                EvidenceRecord,
                FeedbackRecord,
                FeedbackAction,
                ReviewQueueItem,
                ReviewSchedule,
                SchedulerDecision,
            )
        }

    original_schedule = schedule_for_evidence

    def fail_schedule(
        session: Session, *, attempt: Attempt, evidence_record: EvidenceRecord
    ) -> None:
        if failure_point == "after-scheduling":
            original_schedule(session, attempt=attempt, evidence_record=evidence_record)
            session.flush()
            assert session.scalar(select(ReviewQueueItem)) is not None
            assert session.scalar(select(SchedulerDecision)) is not None
        raise RuntimeError("private scheduler failure details")

    with monkeypatch.context() as patch:
        patch.setattr(scoring_module, "schedule_for_evidence", fail_schedule)
        response = client.post("/rubric-scores", json=payload)

    assert response.status_code == 500, response.text
    assert response.json()["detail"] == "Rubric scheduling failed; the score was not saved."
    assert "private scheduler" not in response.text
    # Fresh-session reads distinguish rolled-back writes from cached ORM state.
    with session_factory() as session:
        assert session.get(Attempt, attempt_id) is not None
        assert session.scalar(select(RubricScore)) is None
        assert session.scalar(select(EvidenceRecord)) is None
        for model, ids in baseline_ids.items():
            assert set(session.scalars(select(model.id))) == ids, model.__name__

    retry = client.post("/rubric-scores", json=payload)
    assert retry.status_code == 201, retry.text
    evidence_id = retry.json()["evidence_record_id"]
    with session_factory() as session:
        assert len(list(session.scalars(select(RubricScore)))) == 1
        assert len(list(session.scalars(select(EvidenceRecord)))) == 1
        item = session.scalar(select(ReviewQueueItem))
        assert item is not None
        assert item.source_evidence_record_id == evidence_id
        assert session.get(FeedbackRecord, retry.json()["feedback_record_id"]) is not None

    duplicate = client.post("/rubric-scores", json=payload)
    assert duplicate.status_code == 409, duplicate.text
