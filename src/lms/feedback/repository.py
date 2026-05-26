"""Repository helpers for durable feedback records and actions."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from lms.evidence.models import Attempt
from lms.feedback.models import FeedbackAction, FeedbackRecord


def create_feedback_record(
    session: Session,
    *,
    learner_id: str,
    goal: str,
    observed_evidence: str,
    attempt_id: str | None = None,
    prompt_id: str | None = None,
    evidence_record_id: str | None = None,
    feedback_level: str = "coaching",
    diagnosis: str | None = None,
    gap: str | None = None,
    source_feedback: dict[str, Any] | None = None,
    next_action_ids: list[str] | None = None,
) -> FeedbackRecord:
    """Persist one durable feedback diagnosis."""
    record = FeedbackRecord(
        learner_id=learner_id,
        attempt_id=attempt_id,
        prompt_id=prompt_id,
        evidence_record_id=evidence_record_id,
        feedback_level=feedback_level,
        goal=goal,
        observed_evidence=observed_evidence,
        diagnosis=diagnosis,
        gap=gap,
        source_feedback=source_feedback
        or {
            "goal": goal,
            "observed_evidence": observed_evidence,
            "gap": gap,
        },
        next_action_ids=next_action_ids or [],
    )
    session.add(record)
    session.flush()
    return record


def create_feedback_action(
    session: Session,
    *,
    learner_id: str,
    action_type: str,
    title: str,
    feedback_record_id: str | None = None,
    attempt_id: str | None = None,
    prompt_id: str | None = None,
    status: str = "open",
    instructions: str | None = None,
    due_at: datetime | None = None,
    action_metadata: dict[str, Any] | None = None,
) -> FeedbackAction:
    """Persist one actionable follow-up for learner feedback."""
    action = FeedbackAction(
        feedback_record_id=feedback_record_id,
        learner_id=learner_id,
        attempt_id=attempt_id,
        prompt_id=prompt_id,
        action_type=action_type,
        status=status,
        title=title,
        instructions=instructions,
        due_at=due_at,
        action_metadata=action_metadata,
    )
    session.add(action)
    session.flush()
    return action


def promote_attempt_feedback(
    session: Session,
    attempt: Attempt,
    *,
    evidence_record_id: str | None = None,
) -> FeedbackRecord:
    """Promote legacy Attempt.feedback into durable record/action rows."""
    source_feedback = dict(attempt.feedback)
    next_action = str(source_feedback.get("next_action", "")).strip()
    goal = str(source_feedback.get("goal") or "Review learner response")
    observed_evidence = str(
        source_feedback.get("observed_evidence") or attempt.response_text or next_action
    )
    feedback_level = "remediation" if source_feedback.get("gap") else "coaching"
    record = create_feedback_record(
        session,
        learner_id=attempt.learner_id,
        attempt_id=attempt.id,
        prompt_id=attempt.prompt_id,
        evidence_record_id=evidence_record_id,
        feedback_level=feedback_level,
        goal=goal,
        observed_evidence=observed_evidence,
        diagnosis=observed_evidence,
        gap=source_feedback.get("gap"),
        source_feedback=source_feedback,
    )
    if next_action:
        action = create_feedback_action(
            session,
            feedback_record_id=record.id,
            learner_id=attempt.learner_id,
            attempt_id=attempt.id,
            prompt_id=attempt.prompt_id,
            action_type="prerequisite-remediation" if source_feedback.get("gap") else "retry",
            title=next_action,
            instructions=next_action,
            action_metadata={"source": "attempt.feedback"},
        )
        record.next_action_ids = [action.id]
        session.flush()
    return record


def get_feedback_record(session: Session, feedback_record_id: str) -> FeedbackRecord | None:
    """Return one feedback record by id."""
    return session.get(FeedbackRecord, feedback_record_id)


def get_feedback_action(session: Session, feedback_action_id: str) -> FeedbackAction | None:
    """Return one feedback action by id."""
    return session.get(FeedbackAction, feedback_action_id)


def list_feedback_records(
    session: Session,
    *,
    learner_id: str | None = None,
    attempt_id: str | None = None,
    prompt_id: str | None = None,
    feedback_level: str | None = None,
    limit: int = 100,
) -> Sequence[FeedbackRecord]:
    """List feedback records with common learner-loop filters."""
    statement = select(FeedbackRecord)
    if learner_id is not None:
        statement = statement.where(FeedbackRecord.learner_id == learner_id)
    if attempt_id is not None:
        statement = statement.where(FeedbackRecord.attempt_id == attempt_id)
    if prompt_id is not None:
        statement = statement.where(FeedbackRecord.prompt_id == prompt_id)
    if feedback_level is not None:
        statement = statement.where(FeedbackRecord.feedback_level == feedback_level)
    statement = statement.order_by(FeedbackRecord.created_at.desc(), FeedbackRecord.id).limit(limit)
    return list(session.scalars(statement))


def list_feedback_actions(
    session: Session,
    *,
    learner_id: str | None = None,
    attempt_id: str | None = None,
    prompt_id: str | None = None,
    feedback_record_id: str | None = None,
    action_type: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> Sequence[FeedbackAction]:
    """List feedback actions with common follow-up filters."""
    statement = select(FeedbackAction)
    if learner_id is not None:
        statement = statement.where(FeedbackAction.learner_id == learner_id)
    if attempt_id is not None:
        statement = statement.where(FeedbackAction.attempt_id == attempt_id)
    if prompt_id is not None:
        statement = statement.where(FeedbackAction.prompt_id == prompt_id)
    if feedback_record_id is not None:
        statement = statement.where(FeedbackAction.feedback_record_id == feedback_record_id)
    if action_type is not None:
        statement = statement.where(FeedbackAction.action_type == action_type)
    if status is not None:
        statement = statement.where(FeedbackAction.status == status)
    statement = statement.order_by(FeedbackAction.created_at.desc(), FeedbackAction.id).limit(limit)
    return list(session.scalars(statement))
