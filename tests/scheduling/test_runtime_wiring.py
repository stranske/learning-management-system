"""Runtime scheduler wiring tests for rubric-scored attempts."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from lms.evidence.repository import create_attempt
from lms.feedback.repository import create_rubric
from lms.feedback.scoring import score_attempt_with_rubric
from lms.graphs.repository import create_knowledge_node
from lms.scheduling.models import ReviewQueueItem
from lms.scheduling.repository import complete_review_queue_item
from lms.scheduling.service import SUCCESS_INTERVALS_DAYS


def test_rubric_scoring_runtime_advances_success_ramp(db_session: Session) -> None:
    """Production scoring plus completion advances 1 -> 3 -> 7 day reviews."""
    rubric_id, criterion_id, node_id = _rubric(db_session)
    due_gaps: list[int] = []
    rules: list[str] = []

    for index in range(3):
        attempt = create_attempt(
            db_session,
            learner_id="learner-runtime",
            prompt_id=f"prompt-runtime-{index}",
            response_text="Correct and well-supported answer.",
            feedback={
                "goal": "Use spaced repetition.",
                "observed_evidence": "Learner answered successfully.",
                "next_action": "Schedule the next review.",
            },
            confidence_rating=5,
        )
        score = score_attempt_with_rubric(
            db_session,
            rubric_id=rubric_id,
            attempt_id=attempt.id,
            scorer_type="human",
            criterion_scores=[
                {
                    "criterion_id": criterion_id,
                    "points": 5,
                    "rationale": "Complete response.",
                }
            ],
        )
        item = db_session.scalar(
            select(ReviewQueueItem).where(
                ReviewQueueItem.source_evidence_record_id == score.evidence_record_id
            )
        )

        assert item is not None
        assert item.knowledge_node_id == node_id
        due_gaps.append(round((item.due_at - item.created_at).total_seconds() / 86400))
        rules.append(item.decision_log["rule"])
        if index < 2:
            complete_review_queue_item(
                db_session,
                review_queue_item_id=item.id,
                actor_id="test:runtime-wiring",
            )
            db_session.flush()

    assert due_gaps == list(SUCCESS_INTERVALS_DAYS[:3])
    assert rules == ["success-ramp-step-0", "success-ramp-step-1", "success-ramp-step-2"]


def _rubric(db_session: Session) -> tuple[str, str, str]:
    node = create_knowledge_node(
        db_session,
        title="Runtime spaced repetition",
        knowledge_type="procedural",
        scope="personal",
        actor_id="user:teacher",
        status="published",
    )
    rubric = create_rubric(
        db_session,
        title="Runtime scheduler rubric",
        ownership_scope="personal",
        authoring_actor="user:teacher",
        knowledge_node_id=node.id,
        criteria=[
            {
                "criterion_order": 1,
                "description": "Successful retrieval.",
                "max_points": 5,
            }
        ],
    )
    return rubric.id, rubric.criteria[0].id, node.id
