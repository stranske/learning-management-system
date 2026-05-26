"""Tests for capability maintenance plans."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from lms.auth.models import User
from lms.capability.repository import (
    create_capability_target,
    create_gap_analysis,
    create_maintenance_plan,
    recompute_capability_estimate,
)
from lms.evidence.repository import create_evidence_record
from lms.graphs.repository import create_knowledge_node
from lms.learners.repository import create_learner_for_user
from lms.scheduling.models import ReviewPolicy, ReviewSchedule, SchedulerDecision


def _gap_analysis_fixture(db_session: Session) -> tuple[str, str]:
    user = User(
        email="maintenance-plan@example.test",
        username="maintenance-plan",
        display_name="Learner",
    )
    db_session.add(user)
    db_session.flush()
    learner = create_learner_for_user(
        db_session,
        user_id=user.id,
        display_name="Learner",
    )
    node = create_knowledge_node(
        db_session,
        title="Explain remediation tradeoffs",
        knowledge_type="conceptual",
        scope="personal",
        actor_id=user.id,
        status="published",
    )
    create_evidence_record(
        db_session,
        learner_id=learner.id,
        knowledge_node_id=node.id,
        knowledge_type="conceptual",
        normalized_score=0.35,
        correctness=False,
    )
    target = create_capability_target(
        db_session,
        learner_id=learner.id,
        title="Explain remediation tradeoffs",
        target_node_ids=[node.id],
        required_evidence_types=["rubric-score"],
        confidence_threshold=0.8,
    )
    estimate = recompute_capability_estimate(db_session, target_id=target.id)
    analysis = create_gap_analysis(db_session, estimate_id=estimate.id)
    return analysis.id, node.id


def test_maintenance_plan_turns_gap_items_into_scheduler_steps(db_session: Session) -> None:
    """A gap analysis becomes scheduled, explainable maintenance work."""
    analysis_id, node_id = _gap_analysis_fixture(db_session)
    fixed_now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)

    plan = create_maintenance_plan(db_session, gap_analysis_id=analysis_id, now=fixed_now)

    assert plan.status == "active"
    assert plan.ownership_scope == "personal"
    assert plan.schedule_ids
    remediation_steps = [step for step in plan.plan_steps if step["reason_code"] == "remediation"]
    assert remediation_steps
    remediation_step = remediation_steps[0]
    assert remediation_step["knowledge_node_id"] == node_id
    assert remediation_step["review_schedule_id"] in plan.schedule_ids
    assert remediation_step["review_queue_item_id"]
    assert remediation_step["scheduler_decision_id"]

    decision = db_session.scalar(
        select(SchedulerDecision).where(
            SchedulerDecision.id == remediation_step["scheduler_decision_id"]
        )
    )
    assert decision is not None
    assert decision.reason_code == "remediation"
    assert decision.review_schedule_id == remediation_step["review_schedule_id"]
    assert decision.decision_log["gap_analysis_id"] == analysis_id
    assert decision.decision_log["maintenance_plan_id"] == plan.id

    policy = db_session.get(ReviewPolicy, decision.review_policy_id)
    assert policy is not None
    assert policy.settings == {"source": "gap-analysis"}

    schedule = db_session.scalar(
        select(ReviewSchedule).where(ReviewSchedule.id == remediation_step["review_schedule_id"])
    )
    assert schedule is not None
    assert schedule.reason_code == "remediation"
    assert schedule.due_at.replace(tzinfo=UTC) == fixed_now
