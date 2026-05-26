"""Repository helpers for review queue items."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from lms.scheduling.models import ReviewPolicy, ReviewQueueItem, ReviewSchedule, SchedulerDecision


def create_review_queue_item(
    session: Session,
    *,
    learner_id: str,
    knowledge_node_id: str,
    reason_code: str,
    reason_explanation: str,
    due_at: datetime,
    decision_log: dict[str, Any],
    priority: float = 0.5,
    status: str = "pending",
    source_attempt_id: str | None = None,
    source_evidence_record_id: str | None = None,
) -> ReviewQueueItem:
    """Persist a review queue item."""
    item = ReviewQueueItem(
        learner_id=learner_id,
        knowledge_node_id=knowledge_node_id,
        reason_code=reason_code,
        reason_explanation=reason_explanation,
        due_at=due_at,
        decision_log=decision_log,
        priority=priority,
        status=status,
        source_attempt_id=source_attempt_id,
        source_evidence_record_id=source_evidence_record_id,
    )
    session.add(item)
    session.flush()
    return item


def list_review_queue_for_learner(
    session: Session,
    *,
    learner_id: str,
    status: str | None = "pending",
    limit: int = 100,
) -> Sequence[ReviewQueueItem]:
    """Return queue items for a learner ordered by due date then priority."""
    statement = select(ReviewQueueItem).where(ReviewQueueItem.learner_id == learner_id)
    if status is not None:
        statement = statement.where(ReviewQueueItem.status == status)
    statement = statement.order_by(
        ReviewQueueItem.due_at.asc(),
        ReviewQueueItem.priority.desc(),
        ReviewQueueItem.id,
    ).limit(limit)
    return list(session.scalars(statement))


def count_review_queue_for_learner(
    session: Session,
    *,
    learner_id: str,
    status: str | None = "pending",
) -> int:
    """Count queue items for a learner, optionally filtered by status."""
    statement = (
        select(func.count())
        .select_from(ReviewQueueItem)
        .where(ReviewQueueItem.learner_id == learner_id)
    )
    if status is not None:
        statement = statement.where(ReviewQueueItem.status == status)
    return int(session.scalar(statement) or 0)


def get_or_create_review_policy(
    session: Session,
    *,
    reason_code: str,
    policy_version: str,
    name: str,
    settings: dict[str, Any],
    knowledge_type: str | None = None,
    ownership_scope: str | None = None,
) -> ReviewPolicy:
    """Return an active policy row matching the version/scope or create it.

    The (reason_code, policy_version, knowledge_type, ownership_scope) tuple is
    protected by a partial unique index on active rows, so concurrent callers
    that miss the initial SELECT will race on insert; the loser catches the
    resulting ``IntegrityError`` inside a SAVEPOINT and re-queries the winner.
    """
    statement = select(ReviewPolicy).where(
        ReviewPolicy.reason_code == reason_code,
        ReviewPolicy.policy_version == policy_version,
        ReviewPolicy.knowledge_type.is_(knowledge_type)
        if knowledge_type is None
        else ReviewPolicy.knowledge_type == knowledge_type,
        ReviewPolicy.ownership_scope.is_(ownership_scope)
        if ownership_scope is None
        else ReviewPolicy.ownership_scope == ownership_scope,
        ReviewPolicy.is_active.is_(True),
    )
    existing = session.scalar(statement)
    if existing is not None:
        return existing

    policy = ReviewPolicy(
        name=name,
        policy_version=policy_version,
        reason_code=reason_code,
        knowledge_type=knowledge_type,
        ownership_scope=ownership_scope,
        settings=settings,
    )
    try:
        with session.begin_nested():
            session.add(policy)
            session.flush()
    except IntegrityError:
        winner = session.scalar(statement)
        if winner is not None:
            return winner
        raise
    return policy


def create_review_schedule(
    session: Session,
    *,
    learner_id: str,
    knowledge_node_id: str,
    reason_code: str,
    due_at: datetime,
    policy_version: str,
    review_policy_id: str | None = None,
    review_queue_item_id: str | None = None,
    knowledge_type: str | None = None,
    ownership_scope: str | None = None,
    source_evidence_record_id: str | None = None,
    schedule_state: str = "scheduled",
) -> ReviewSchedule:
    """Persist a durable schedule row for a queue decision."""
    schedule = ReviewSchedule(
        learner_id=learner_id,
        knowledge_node_id=knowledge_node_id,
        review_policy_id=review_policy_id,
        review_queue_item_id=review_queue_item_id,
        reason_code=reason_code,
        schedule_state=schedule_state,
        due_at=due_at,
        policy_version=policy_version,
        knowledge_type=knowledge_type,
        ownership_scope=ownership_scope,
        source_evidence_record_id=source_evidence_record_id,
    )
    session.add(schedule)
    session.flush()
    return schedule


def create_scheduler_decision(
    session: Session,
    *,
    learner_id: str,
    knowledge_node_id: str,
    reason_code: str,
    decision_rationale: str,
    policy_version: str,
    decision_log: dict[str, Any],
    review_policy_id: str | None = None,
    review_schedule_id: str | None = None,
    review_queue_item_id: str | None = None,
    source_evidence_record_id: str | None = None,
    knowledge_type: str | None = None,
    ownership_scope: str | None = None,
    support_level: str | None = None,
) -> SchedulerDecision:
    """Persist an explainable scheduler decision row."""
    decision = SchedulerDecision(
        learner_id=learner_id,
        knowledge_node_id=knowledge_node_id,
        review_policy_id=review_policy_id,
        review_schedule_id=review_schedule_id,
        review_queue_item_id=review_queue_item_id,
        source_evidence_record_id=source_evidence_record_id,
        reason_code=reason_code,
        decision_rationale=decision_rationale,
        policy_version=policy_version,
        knowledge_type=knowledge_type,
        ownership_scope=ownership_scope,
        support_level=support_level,
        decision_log=decision_log,
    )
    session.add(decision)
    session.flush()
    return decision


def list_review_policies(
    session: Session,
    *,
    reason_code: str | None = None,
    active_only: bool = True,
    limit: int = 100,
) -> Sequence[ReviewPolicy]:
    """List scheduler policy records."""
    statement = select(ReviewPolicy)
    if reason_code is not None:
        statement = statement.where(ReviewPolicy.reason_code == reason_code)
    if active_only:
        statement = statement.where(ReviewPolicy.is_active.is_(True))
    statement = statement.order_by(ReviewPolicy.created_at.desc(), ReviewPolicy.id).limit(limit)
    return list(session.scalars(statement))


def list_review_schedules(
    session: Session,
    *,
    learner_id: str | None = None,
    knowledge_node_id: str | None = None,
    schedule_state: str | None = None,
    limit: int = 100,
) -> Sequence[ReviewSchedule]:
    """List durable schedule records with optional learner/node filters."""
    statement = select(ReviewSchedule)
    if learner_id is not None:
        statement = statement.where(ReviewSchedule.learner_id == learner_id)
    if knowledge_node_id is not None:
        statement = statement.where(ReviewSchedule.knowledge_node_id == knowledge_node_id)
    if schedule_state is not None:
        statement = statement.where(ReviewSchedule.schedule_state == schedule_state)
    statement = statement.order_by(
        ReviewSchedule.due_at.asc(),
        ReviewSchedule.created_at.asc(),
        ReviewSchedule.id,
    ).limit(limit)
    return list(session.scalars(statement))


def list_scheduler_decisions(
    session: Session,
    *,
    learner_id: str | None = None,
    knowledge_node_id: str | None = None,
    reason_code: str | None = None,
    limit: int = 100,
) -> Sequence[SchedulerDecision]:
    """List explainable scheduler decisions with optional filters."""
    statement = select(SchedulerDecision)
    if learner_id is not None:
        statement = statement.where(SchedulerDecision.learner_id == learner_id)
    if knowledge_node_id is not None:
        statement = statement.where(SchedulerDecision.knowledge_node_id == knowledge_node_id)
    if reason_code is not None:
        statement = statement.where(SchedulerDecision.reason_code == reason_code)
    statement = statement.order_by(
        SchedulerDecision.created_at.desc(),
        SchedulerDecision.id,
    ).limit(limit)
    return list(session.scalars(statement))
