"""Regression coverage for rubric scoring's production scheduling seam."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from lms.evidence.repository import create_attempt
from lms.feedback.repository import create_rubric
from lms.feedback.scoring import score_attempt_with_rubric
from lms.graphs.repository import create_knowledge_node
from lms.scheduling.models import ReviewQueueItem
from lms.scheduling.repository import create_remediation_trigger


def test_rubric_score_fires_configured_remediation_trigger(db_session: Session) -> None:
    """Rubric scoring sends matching evidence through deterministic triggers."""
    node = create_knowledge_node(
        db_session,
        title="Rubric remediation node",
        knowledge_type="procedural",
        scope="personal",
        actor_id="user:alice",
        status="published",
    )
    rubric = create_rubric(
        db_session,
        title="Rubric remediation",
        ownership_scope="personal",
        authoring_actor="user:alice",
        knowledge_node_id=node.id,
        criteria=[
            {
                "criterion_order": 1,
                "description": "Shows the reasoning.",
                "max_points": 2,
            }
        ],
    )
    trigger = create_remediation_trigger(
        db_session,
        knowledge_node_id=node.id,
        trigger_type="high-confidence-error",
        trigger_rules={"min_confidence": 4},
        ownership_scope="personal",
    )
    attempt = create_attempt(
        db_session,
        learner_id="learner-rubric-remediation",
        prompt_id="prompt-rubric-remediation",
        response_text="A confident but incorrect explanation.",
        confidence_rating=5,
        feedback={
            "goal": "Practice the reasoning",
            "observed_evidence": "Incorrect rubric response.",
            "next_action": "Review the prerequisite.",
        },
    )

    score_attempt_with_rubric(
        db_session,
        rubric_id=rubric.id,
        attempt_id=attempt.id,
        scorer_type="human",
        criterion_scores=[{"criterion_id": rubric.criteria[0].id, "points": 0}],
    )

    items = list(
        db_session.scalars(
            select(ReviewQueueItem)
            .where(ReviewQueueItem.learner_id == attempt.learner_id)
            .order_by(ReviewQueueItem.created_at)
        )
    )
    trigger_items = [
        item for item in items if item.decision_log.get("signal") == "remediation-trigger"
    ]
    assert len(trigger_items) == 1
    assert trigger_items[0].knowledge_node_id == node.id
    assert trigger_items[0].decision_log["inputs"]["trigger_id"] == trigger.id
