"""HTTP regression gate for rubric scoring's production scheduling seam.

Issue #573's original failing-main expectation predates the wiring fix in
PR #576. This gate now passes on the fixed implementation and must fail if
scoring bypasses schedule_for_evidence or apply_remediation_triggers is disabled.

Issue #837 repair: rubric-scored evidence keeps correctness=None for FSRS bands,
so correctness-dependent triggers must also honor normalized_score below the
configured feedback threshold.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from lms.evidence.models import EvidenceRecord
from lms.feedback.repository import create_rubric
from lms.graphs.repository import create_knowledge_node
from lms.scheduling.models import ReviewQueueItem
from lms.scheduling.repository import create_remediation_trigger
from lms.scheduling.service import apply_remediation_triggers
from tests.scheduling.test_attempt_to_next_review_e2e import (
    _seed_learner_node_prompt,
    loop_client,  # noqa: F401 -- reuse the isolated production API fixture
)
from tests.scheduling.test_review_queue import _make_attempt


def _attempt_payload(
    learner_id: str,
    prompt_id: str,
    *,
    confidence_rating: int = 5,
    response_metadata: dict[str, object] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "learner_id": learner_id,
        "prompt_id": prompt_id,
        "response_text": "A confident but incorrect explanation.",
        "confidence_rating": confidence_rating,
        "feedback": {
            "goal": "Practice the reasoning",
            "observed_evidence": "Incorrect rubric response.",
            "next_action": "Review the prerequisite.",
        },
    }
    if response_metadata is not None:
        payload["response_metadata"] = response_metadata
    return payload


def _score_rubric(
    client: TestClient,
    *,
    rubric_id: str,
    attempt_id: str,
    criterion_id: str,
    points: int,
    feedback_threshold: float = 0.85,
    remediation_threshold: float = 0.5,
) -> dict[str, object]:
    response = client.post(
        "/rubric-scores",
        json={
            "rubric_id": rubric_id,
            "attempt_id": attempt_id,
            "scorer_type": "human",
            "criterion_scores": [{"criterion_id": criterion_id, "points": points}],
            "feedback_threshold": feedback_threshold,
            "remediation_threshold": remediation_threshold,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _queue_items_for_learner(
    session_factory: sessionmaker[Session], learner_id: str
) -> list[ReviewQueueItem]:
    with session_factory() as session:
        return list(
            session.scalars(select(ReviewQueueItem).where(ReviewQueueItem.learner_id == learner_id))
        )


def _split_queue_items(
    items: list[ReviewQueueItem],
) -> tuple[list[ReviewQueueItem], list[ReviewQueueItem]]:
    fsrs_items = [
        item
        for item in items
        if isinstance(item.decision_log, dict) and "fsrs_rating" in item.decision_log
    ]
    trigger_items = [
        item
        for item in items
        if isinstance(item.decision_log, dict)
        and item.decision_log.get("signal") == "remediation-trigger"
    ]
    return fsrs_items, trigger_items


def test_rubric_high_confidence_error_missing_without_below_feedback_predicate(
    db_session: Session,
) -> None:
    """Main before #837 repair: null rubric correctness never matches this trigger."""
    node = create_knowledge_node(
        db_session,
        title="Rubric trigger gap",
        knowledge_type="conceptual",
        scope="personal",
        actor_id="user:alice",
        status="published",
    )
    attempt, evidence = _make_attempt(
        db_session,
        learner_id="learner-rubric-gap",
        knowledge_node_id=node.id,
        correctness=None,
        normalized_score=0.2,
        confidence_rating=5,
    )
    create_remediation_trigger(
        db_session,
        knowledge_node_id=node.id,
        trigger_type="high-confidence-error",
        trigger_rules={"min_confidence": 4},
        ownership_scope="personal",
    )
    items = apply_remediation_triggers(db_session, attempt=attempt, evidence_record=evidence)
    assert items == []


def test_rubric_score_fires_high_confidence_error_below_feedback_threshold(
    loop_client: tuple[TestClient, sessionmaker[Session]],  # noqa: F811
) -> None:
    """Unassisted HTTP rubric score below feedback threshold fires the trigger."""
    client, session_factory = loop_client
    learner_id, node_id, prompt_id = _seed_learner_node_prompt(session_factory)
    with session_factory() as session:
        rubric = create_rubric(
            session,
            title="Rubric remediation",
            ownership_scope="personal",
            authoring_actor="system:e2e-loop-test",
            knowledge_node_id=node_id,
            criteria=[
                {
                    "criterion_order": 1,
                    "description": "Shows the reasoning.",
                    "max_points": 2,
                }
            ],
        )
        trigger = create_remediation_trigger(
            session,
            knowledge_node_id=node_id,
            trigger_type="high-confidence-error",
            trigger_rules={"min_confidence": 4},
            ownership_scope="personal",
        )
        session.commit()
        rubric_id, criterion_id, trigger_id = rubric.id, rubric.criteria[0].id, trigger.id

    attempt_response = client.post(
        "/attempts",
        json=_attempt_payload(learner_id, prompt_id, confidence_rating=5),
    )
    assert attempt_response.status_code == 201, attempt_response.text
    attempt_id = attempt_response.json()["id"]
    with session_factory() as session:
        assert (
            session.scalar(select(ReviewQueueItem).where(ReviewQueueItem.learner_id == learner_id))
            is None
        )

    body = _score_rubric(
        client,
        rubric_id=rubric_id,
        attempt_id=attempt_id,
        criterion_id=criterion_id,
        points=0,
    )
    evidence_id = str(body["evidence_record_id"])

    with session_factory() as session:
        evidence = session.get(EvidenceRecord, evidence_id)
        assert evidence is not None
        assert evidence.scoring_method == "rubric-scored"
        assert evidence.correctness is None

    fsrs_items, trigger_items = _split_queue_items(
        _queue_items_for_learner(session_factory, learner_id)
    )
    assert len(fsrs_items) == 1
    assert fsrs_items[0].source_evidence_record_id == evidence_id
    assert len(trigger_items) == 1, "rubric below feedback must match high-confidence-error"
    item = trigger_items[0]
    assert item.reason_code == "remediation"
    assert item.source_attempt_id == attempt_id
    assert item.source_evidence_record_id == evidence_id
    assert item.decision_log["rule"] == "high-confidence-error"
    assert item.decision_log["inputs"]["trigger_id"] == trigger_id
    assert item.id != fsrs_items[0].id
    assert fsrs_items[0].source_evidence_record_id == evidence_id


@pytest.mark.parametrize(
    ("points", "max_points", "confidence", "expect_trigger", "case_id"),
    [
        (85, 100, 5, False, "at-feedback-boundary"),
        (70, 100, 5, True, "between-feedback-and-remediation"),
        (40, 100, 3, False, "below-minimum-confidence"),
    ],
)
def test_rubric_configured_trigger_respects_score_and_confidence(
    loop_client: tuple[TestClient, sessionmaker[Session]],  # noqa: F811
    points: int,
    max_points: int,
    confidence: int,
    expect_trigger: bool,
    case_id: str,
) -> None:
    client, session_factory = loop_client
    learner_id, node_id, prompt_id = _seed_learner_node_prompt(session_factory)
    with session_factory() as session:
        rubric = create_rubric(
            session,
            title=f"Rubric trigger gate {case_id}",
            ownership_scope="personal",
            authoring_actor="system:e2e-loop-test",
            knowledge_node_id=node_id,
            criteria=[
                {
                    "criterion_order": 1,
                    "description": "Shows the reasoning.",
                    "max_points": max_points,
                }
            ],
        )
        create_remediation_trigger(
            session,
            knowledge_node_id=node_id,
            trigger_type="high-confidence-error",
            trigger_rules={"min_confidence": 4},
            ownership_scope="personal",
        )
        session.commit()
        rubric_id, criterion_id = rubric.id, rubric.criteria[0].id

    attempt_response = client.post(
        "/attempts",
        json=_attempt_payload(learner_id, prompt_id, confidence_rating=confidence),
    )
    assert attempt_response.status_code == 201, attempt_response.text
    attempt_id = attempt_response.json()["id"]

    _score_rubric(
        client,
        rubric_id=rubric_id,
        attempt_id=attempt_id,
        criterion_id=criterion_id,
        points=points,
    )

    _fsrs, trigger_items = _split_queue_items(_queue_items_for_learner(session_factory, learner_id))
    if expect_trigger:
        assert len(trigger_items) == 1
        assert trigger_items[0].decision_log["rule"] == "high-confidence-error"
    else:
        assert trigger_items == []


@pytest.mark.parametrize(
    ("failed_ids", "expect_trigger"),
    [
        (["node-prereq"], True),
        (["node-other"], False),
    ],
)
def test_rubric_failed_prerequisite_trigger_metadata_matching(
    loop_client: tuple[TestClient, sessionmaker[Session]],  # noqa: F811
    failed_ids: list[str],
    expect_trigger: bool,
) -> None:
    client, session_factory = loop_client
    learner_id, node_id, prompt_id = _seed_learner_node_prompt(session_factory)
    prereq_id = "node-prereq"
    with session_factory() as session:
        rubric = create_rubric(
            session,
            title="Rubric prerequisite trigger",
            ownership_scope="personal",
            authoring_actor="system:e2e-loop-test",
            knowledge_node_id=node_id,
            criteria=[
                {
                    "criterion_order": 1,
                    "description": "Shows the reasoning.",
                    "max_points": 2,
                }
            ],
        )
        trigger = create_remediation_trigger(
            session,
            knowledge_node_id=node_id,
            trigger_type="failed-prerequisite",
            trigger_rules={"prerequisite_node_id": prereq_id},
            ownership_scope="personal",
        )
        session.commit()
        rubric_id, criterion_id, trigger_id = rubric.id, rubric.criteria[0].id, trigger.id

    attempt_response = client.post(
        "/attempts",
        json=_attempt_payload(
            learner_id,
            prompt_id,
            confidence_rating=4,
            response_metadata={"failed_prerequisite_ids": failed_ids},
        ),
    )
    assert attempt_response.status_code == 201, attempt_response.text
    attempt_id = attempt_response.json()["id"]

    body = _score_rubric(
        client,
        rubric_id=rubric_id,
        attempt_id=attempt_id,
        criterion_id=criterion_id,
        points=0,
    )
    evidence_id = str(body["evidence_record_id"])

    _fsrs, trigger_items = _split_queue_items(_queue_items_for_learner(session_factory, learner_id))
    if expect_trigger:
        assert len(trigger_items) == 1
        item = trigger_items[0]
        assert item.decision_log["rule"] == "failed-prerequisite"
        assert item.decision_log["inputs"]["trigger_id"] == trigger_id
        assert item.source_evidence_record_id == evidence_id
    else:
        assert trigger_items == []
