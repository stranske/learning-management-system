"""HTTP regression gate for rubric scoring's production scheduling seam.

Issue #573's original failing-main expectation predates the wiring fix in
PR #576. This gate now passes on the fixed implementation and must fail if
scoring bypasses schedule_for_evidence or apply_remediation_triggers is disabled.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from lms.evidence.models import EvidenceRecord
from lms.feedback.repository import create_rubric
from lms.scheduling.models import ReviewQueueItem
from lms.scheduling.repository import create_remediation_trigger
from tests.scheduling.test_attempt_to_next_review_e2e import (
    _seed_learner_node_prompt,
    loop_client,  # noqa: F401 -- reuse the isolated production API fixture
)


def test_rubric_score_fires_configured_remediation_trigger(
    loop_client: tuple[TestClient, sessionmaker[Session]],  # noqa: F811
) -> None:
    """A rubric HTTP score commits a trigger item linked to its own evidence."""
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

    # An unscored attempt must not create the item we later attribute to rubric scoring.
    attempt_response = client.post(
        "/attempts",
        json={
            "learner_id": learner_id,
            "prompt_id": prompt_id,
            "response_text": "A confident but incorrect explanation.",
            "confidence_rating": 5,
            "feedback": {
                "goal": "Practice the reasoning",
                "observed_evidence": "Incorrect rubric response.",
                "next_action": "Review the prerequisite.",
            },
        },
    )
    assert attempt_response.status_code == 201, attempt_response.text
    attempt_id = attempt_response.json()["id"]
    with session_factory() as session:
        assert (
            session.scalar(select(ReviewQueueItem).where(ReviewQueueItem.learner_id == learner_id))
            is None
        )

    response = client.post(
        "/rubric-scores",
        json={
            "rubric_id": rubric_id,
            "attempt_id": attempt_id,
            "scorer_type": "human",
            "criterion_scores": [{"criterion_id": criterion_id, "points": 0}],
        },
    )
    assert response.status_code == 201, response.text
    evidence_id = response.json()["evidence_record_id"]

    # Read through a fresh session to verify the route committed actual persisted rows.
    with session_factory() as session:
        evidence = session.get(EvidenceRecord, evidence_id)
        assert evidence is not None
        assert evidence.attempt_id == attempt_id
        assert evidence.scoring_method == "rubric-scored"
        assert evidence.correctness is False
        items = list(
            session.scalars(select(ReviewQueueItem).where(ReviewQueueItem.learner_id == learner_id))
        )
        trigger_items = [
            item for item in items if item.decision_log.get("signal") == "remediation-trigger"
        ]
        assert len(trigger_items) == 1, "rubric scoring must persist its configured trigger item"
        item = trigger_items[0]
        assert item.reason_code == "remediation"
        assert item.knowledge_node_id == node_id
        assert item.source_attempt_id == attempt_id
        assert item.source_evidence_record_id == evidence_id
        assert item.decision_log["rule"] == "high-confidence-error"
        assert item.decision_log["inputs"]["trigger_id"] == trigger_id
