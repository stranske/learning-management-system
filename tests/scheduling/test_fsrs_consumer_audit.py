"""Audit evidence ratings through the real HTTP, FSRS and persistence boundary."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from lms.evidence.models import Attempt, EvidenceRecord
from lms.scheduling import fsrs_engine
from lms.scheduling.models import (
    ReviewCardState,
    ReviewQueueItem,
    ReviewSchedule,
    SchedulerDecision,
)
from tests.scheduling.test_attempt_to_next_review_e2e import (
    _attempt_payload,
    _clone_timing_prompt,
    _seed_learner_node_prompt,
)
from tests.scheduling.test_attempt_to_next_review_e2e import (
    loop_client as loop_client,
)


def _scheduling_rows(session: Session, learner: str, node: str) -> dict[str, Any]:
    """Snapshot every persisted row for this learner/node, including old attempts."""
    result: dict[str, Any] = {}
    for model in (ReviewQueueItem, ReviewSchedule, SchedulerDecision):
        rows = session.scalars(
            select(model).where(model.learner_id == learner, model.knowledge_node_id == node)
        )
        result[model.__tablename__] = {
            row.id: deepcopy(
                {column.key: getattr(row, column.key) for column in model.__table__.columns}
            )
            for row in rows
        }
    return result


@pytest.mark.parametrize(
    ("change", "rule", "rating"),
    [
        pytest.param({"transfer_distance": "near"}, "transfer-excluded", None, id="near"),
        pytest.param({"transfer_distance": "far"}, "transfer-excluded", None, id="far"),
        pytest.param({"transfer_distance": "novel"}, "transfer-excluded", None, id="novel"),
        pytest.param({"correctness": False}, "incorrect", 1, id="incorrect"),
        pytest.param({"hint_used": True}, "supported-or-low-confidence-correct", 2, id="hint"),
        pytest.param(
            {"reference_accessed": True}, "supported-or-low-confidence-correct", 2, id="reference"
        ),
        pytest.param({"normalized_score": 0.49}, "partial-under-half", 1, id="under-half"),
        pytest.param({"normalized_score": 0.50}, "partial-under-mastery", 2, id="half"),
        pytest.param({"normalized_score": 0.84}, "partial-under-mastery", 2, id="under-mastery"),
        pytest.param(
            {"normalized_score": 0.85, "scoring_method": "partial-credit"},
            "partial-at-mastery",
            3,
            id="mastery",
        ),
        pytest.param({}, "unsupported-correct", 3, id="good"),
        pytest.param({"confidence_rating": 5}, "fast-first-attempt", 4, id="easy"),
    ],
)
def test_rating_inventory_reaches_persisted_consumers(
    loop_client: tuple[TestClient, sessionmaker[Session]],
    monkeypatch: pytest.MonkeyPatch,
    change: dict[str, Any],
    rule: str,
    rating: int | None,
) -> None:
    client, factory = loop_client
    learner, node, prompt = _seed_learner_node_prompt(factory)
    # Establish real timing history on other prompts before observing the target.
    # It makes Easy reachable without replacing the timing selector or scheduler.
    for _ in range(3):
        prior_prompt, prior_node = _clone_timing_prompt(factory, prompt)
        prior = _attempt_payload(learner, prior_node, prior_prompt, response_text="timing")
        prior.update(confidence_rating=5, elapsed_seconds=40)
        response = client.post("/attempts", json=prior)
        assert response.status_code == 201, response.text

    with factory() as session:
        before_rows = _scheduling_rows(session, learner, node)
        before_card = session.scalars(
            select(ReviewCardState).where(ReviewCardState.subject_id == node)
        ).one()
        before = deepcopy(
            {
                column.key: getattr(before_card, column.key)
                for column in ReviewCardState.__table__.columns
            }
        )

    observed: list[int] = []
    real_review = fsrs_engine.review

    def recording_review(**kwargs: Any) -> Any:
        observed.append(kwargs["rating_value"])
        return real_review(**kwargs)

    monkeypatch.setattr(fsrs_engine, "review", recording_review)
    payload = _attempt_payload(learner, node, prompt, response_text="audited evidence")
    payload["elapsed_seconds"] = 1
    evidence_payload = payload["evidence"]
    assert isinstance(evidence_payload, dict)
    for key, value in change.items():
        if key in {"confidence_rating", "hint_used", "reference_accessed"}:
            payload[key] = value
        else:
            evidence_payload[key] = value
    response = client.post("/attempts", json=payload)
    assert response.status_code == 201, response.text
    attempt_id = response.json()["id"]

    # Read after the HTTP transaction committed. Queue/schedule/decision rows
    # must belong to this attempt; timing history shares the same subject.
    with factory() as session:
        attempt = session.get(Attempt, attempt_id)
        assert attempt is not None
        evidence = session.scalars(
            select(EvidenceRecord).where(EvidenceRecord.attempt_id == attempt_id)
        ).one()
        cards = list(
            session.scalars(select(ReviewCardState).where(ReviewCardState.subject_id == node))
        )
        queue = list(
            session.scalars(
                select(ReviewQueueItem).where(ReviewQueueItem.source_attempt_id == attempt_id)
            )
        )
        schedules = list(
            session.scalars(
                select(ReviewSchedule)
                .join(ReviewQueueItem, ReviewSchedule.review_queue_item_id == ReviewQueueItem.id)
                .where(ReviewQueueItem.source_attempt_id == attempt_id)
            )
        )
        decisions = list(
            session.scalars(
                select(SchedulerDecision)
                .join(ReviewQueueItem, SchedulerDecision.review_queue_item_id == ReviewQueueItem.id)
                .where(ReviewQueueItem.source_attempt_id == attempt_id)
            )
        )
        if rating is None:
            assert _scheduling_rows(session, learner, node) == before_rows
            assert observed == []
            assert not queue
            assert not schedules
            assert not decisions
            assert len(cards) == 1
            assert {
                column.key: getattr(cards[0], column.key)
                for column in ReviewCardState.__table__.columns
            } == before
            assert attempt.response_metadata is not None
            receipt = attempt.response_metadata["scheduling_outcome"]
            assert receipt["fsrs_rating"]["rule_id"] == rule
            assert receipt["fsrs_rating"]["scheduling_included"] is False
            assert receipt["card_mutated"] is False
            assert receipt["output"]["due_at"] is None
            return
        assert observed == [rating]
        assert len(cards) == len(queue) == len(schedules) == len(decisions) == 1
        item, card, schedule, decision = queue[0], cards[0], schedules[0], decisions[0]
        assert item.source_evidence_record_id == evidence.id
        assert item.decision_log["fsrs_rating"]["rule_id"] == rule
        assert item.decision_log["fsrs_rating"]["value"] == rating
        assert card.review_count == before["review_count"] + 1
        assert card.due_at is not None
        assert card.card_state
        assert schedule.due_at == item.due_at
        assert decision.review_queue_item_id == item.id
        assert decision.review_schedule_id == schedule.id
