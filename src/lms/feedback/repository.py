"""Repository helpers for durable feedback records and actions."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from lms.evidence.models import Attempt
from lms.feedback.models import FeedbackAction, FeedbackRecord, Rubric, RubricCriterion, RubricScore
from lms.graphs.models import OWNERSHIP_SCOPES, KnowledgeNode
from lms.prompts.models import Prompt


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
    diagnosis_value = source_feedback.get("diagnosis")
    diagnosis = str(diagnosis_value) if diagnosis_value else None
    record = create_feedback_record(
        session,
        learner_id=attempt.learner_id,
        attempt_id=attempt.id,
        prompt_id=attempt.prompt_id,
        evidence_record_id=evidence_record_id,
        feedback_level=feedback_level,
        goal=goal,
        observed_evidence=observed_evidence,
        diagnosis=diagnosis,
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


def create_rubric(
    session: Session,
    *,
    title: str,
    ownership_scope: str,
    authoring_actor: str,
    description: str | None = None,
    prompt_id: str | None = None,
    knowledge_node_id: str | None = None,
    case_id: str | None = None,
    status: str = "draft",
    reviewing_actor: str | None = None,
    criteria: list[dict[str, Any]] | None = None,
) -> Rubric:
    """Create a rubric with optional nested criteria."""
    _validate_rubric_links(
        session,
        ownership_scope=ownership_scope,
        prompt_id=prompt_id,
        knowledge_node_id=knowledge_node_id,
    )
    _require_unique_criterion_orders(criteria or [])
    rubric = Rubric(
        title=title,
        description=description,
        ownership_scope=ownership_scope,
        prompt_id=prompt_id,
        knowledge_node_id=knowledge_node_id,
        case_id=case_id,
        status=status,
        authoring_actor=authoring_actor,
        reviewing_actor=reviewing_actor,
    )
    for criterion_data in sorted(criteria or [], key=lambda item: item["criterion_order"]):
        rubric.criteria.append(RubricCriterion(**criterion_data))
    session.add(rubric)
    session.flush()
    return rubric


def get_rubric(session: Session, rubric_id: str) -> Rubric | None:
    """Return one rubric with criteria loaded in deterministic order."""
    return session.scalar(
        select(Rubric).options(selectinload(Rubric.criteria)).where(Rubric.id == rubric_id)
    )


def list_rubrics(
    session: Session,
    *,
    ownership_scope: str | None = None,
    prompt_id: str | None = None,
    knowledge_node_id: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> Sequence[Rubric]:
    """List rubrics with common authoring filters."""
    statement = select(Rubric).options(selectinload(Rubric.criteria))
    if ownership_scope is not None:
        _require_ownership_scope(ownership_scope)
        statement = statement.where(Rubric.ownership_scope == ownership_scope)
    if prompt_id is not None:
        statement = statement.where(Rubric.prompt_id == prompt_id)
    if knowledge_node_id is not None:
        statement = statement.where(Rubric.knowledge_node_id == knowledge_node_id)
    if status is not None:
        statement = statement.where(Rubric.status == status)
    statement = statement.order_by(Rubric.created_at.desc(), Rubric.id).limit(limit)
    return list(session.scalars(statement))


def update_rubric(
    session: Session,
    rubric: Rubric,
    *,
    title: str | None = None,
    description: str | None = None,
    prompt_id: str | None = None,
    knowledge_node_id: str | None = None,
    case_id: str | None = None,
    status: str | None = None,
    reviewing_actor: str | None = None,
) -> Rubric:
    """Update mutable rubric fields and revalidate linked scope."""
    next_prompt_id = prompt_id if prompt_id is not None else rubric.prompt_id
    next_node_id = knowledge_node_id if knowledge_node_id is not None else rubric.knowledge_node_id
    _validate_rubric_links(
        session,
        ownership_scope=rubric.ownership_scope,
        prompt_id=next_prompt_id,
        knowledge_node_id=next_node_id,
    )
    for field_name, value in {
        "title": title,
        "description": description,
        "prompt_id": prompt_id,
        "knowledge_node_id": knowledge_node_id,
        "case_id": case_id,
        "status": status,
        "reviewing_actor": reviewing_actor,
    }.items():
        if value is not None:
            setattr(rubric, field_name, value)
    session.flush()
    return rubric


def archive_rubric(session: Session, rubric: Rubric) -> Rubric:
    """Archive a rubric and its active criteria."""
    rubric.status = "archived"
    for criterion in rubric.criteria:
        criterion.status = "archived"
    session.flush()
    return rubric


def create_rubric_criterion(
    session: Session,
    *,
    rubric_id: str,
    criterion_order: int,
    description: str,
    max_points: float,
    performance_levels: dict[str, Any] | None = None,
    validity_scope: str | None = None,
    status: str = "active",
) -> RubricCriterion:
    """Create one criterion for an existing rubric."""
    if session.get(Rubric, rubric_id) is None:
        raise ValueError("referenced rubric was not found")
    _require_criterion_order_available(session, rubric_id, criterion_order)
    criterion = RubricCriterion(
        rubric_id=rubric_id,
        criterion_order=criterion_order,
        description=description,
        max_points=max_points,
        performance_levels=performance_levels or {},
        validity_scope=validity_scope,
        status=status,
    )
    session.add(criterion)
    session.flush()
    return criterion


def update_rubric_criterion(
    session: Session,
    criterion: RubricCriterion,
    *,
    criterion_order: int | None = None,
    description: str | None = None,
    max_points: float | None = None,
    performance_levels: dict[str, Any] | None = None,
    validity_scope: str | None = None,
    status: str | None = None,
) -> RubricCriterion:
    """Update mutable criterion fields."""
    if criterion_order is not None and criterion_order != criterion.criterion_order:
        _require_criterion_order_available(session, criterion.rubric_id, criterion_order)
        criterion.criterion_order = criterion_order
    for field_name, value in {
        "description": description,
        "max_points": max_points,
        "performance_levels": performance_levels,
        "validity_scope": validity_scope,
        "status": status,
    }.items():
        if value is not None:
            setattr(criterion, field_name, value)
    session.flush()
    return criterion


def get_rubric_criterion(
    session: Session,
    rubric_id: str,
    criterion_id: str,
) -> RubricCriterion | None:
    """Return one criterion by id only within its parent rubric."""
    return session.scalar(
        select(RubricCriterion).where(
            RubricCriterion.rubric_id == rubric_id,
            RubricCriterion.id == criterion_id,
        )
    )


def list_rubric_criteria(
    session: Session,
    *,
    rubric_id: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> Sequence[RubricCriterion]:
    """List rubric criteria in deterministic order."""
    statement = select(RubricCriterion)
    if rubric_id is not None:
        statement = statement.where(RubricCriterion.rubric_id == rubric_id)
    if status is not None:
        statement = statement.where(RubricCriterion.status == status)
    statement = statement.order_by(
        RubricCriterion.rubric_id, RubricCriterion.criterion_order
    ).limit(limit)
    return list(session.scalars(statement))


def create_rubric_score(
    session: Session,
    *,
    rubric_id: str,
    attempt_id: str,
    learner_id: str,
    scorer_type: str,
    raw_score: float,
    normalized_score: float,
    max_score: float,
    criterion_scores: list[dict[str, Any]],
    scorer_id: str | None = None,
    scorer_version: str | None = None,
    evidence_record_id: str | None = None,
    feedback_record_id: str | None = None,
    score_metadata: dict[str, Any] | None = None,
) -> RubricScore:
    """Persist a criterion-level rubric scoring result."""
    score = RubricScore(
        rubric_id=rubric_id,
        attempt_id=attempt_id,
        learner_id=learner_id,
        scorer_type=scorer_type,
        scorer_id=scorer_id,
        scorer_version=scorer_version,
        raw_score=raw_score,
        normalized_score=normalized_score,
        max_score=max_score,
        criterion_scores=criterion_scores,
        evidence_record_id=evidence_record_id,
        feedback_record_id=feedback_record_id,
        score_metadata=score_metadata,
    )
    session.add(score)
    session.flush()
    return score


def get_rubric_score(session: Session, rubric_score_id: str) -> RubricScore | None:
    """Return one rubric score by id."""
    return session.get(RubricScore, rubric_score_id)


def list_rubric_scores(
    session: Session,
    *,
    rubric_id: str | None = None,
    attempt_id: str | None = None,
    learner_id: str | None = None,
    limit: int = 100,
) -> Sequence[RubricScore]:
    """List rubric scores by rubric, attempt, or learner."""
    statement = select(RubricScore)
    if rubric_id is not None:
        statement = statement.where(RubricScore.rubric_id == rubric_id)
    if attempt_id is not None:
        statement = statement.where(RubricScore.attempt_id == attempt_id)
    if learner_id is not None:
        statement = statement.where(RubricScore.learner_id == learner_id)
    statement = statement.order_by(RubricScore.created_at.desc(), RubricScore.id).limit(limit)
    return list(session.scalars(statement))


def _validate_rubric_links(
    session: Session,
    *,
    ownership_scope: str,
    prompt_id: str | None,
    knowledge_node_id: str | None,
) -> None:
    _require_ownership_scope(ownership_scope)
    if knowledge_node_id is not None:
        node = session.get(KnowledgeNode, knowledge_node_id)
        if node is None:
            raise ValueError("referenced knowledge node was not found")
        if node.ownership_scope != ownership_scope:
            raise ValueError("rubric knowledge node must match the rubric ownership scope")
    if prompt_id is not None:
        prompt = session.get(Prompt, prompt_id)
        if prompt is None:
            raise ValueError("referenced prompt was not found")
        target_node = session.get(KnowledgeNode, prompt.target_node_id)
        if target_node is None or target_node.ownership_scope != ownership_scope:
            raise ValueError("rubric prompt target must match the rubric ownership scope")


def _require_ownership_scope(scope: str) -> None:
    if scope not in OWNERSHIP_SCOPES:
        raise ValueError(f"unknown ownership scope {scope!r}; expected one of {OWNERSHIP_SCOPES}")


def _require_unique_criterion_orders(criteria: list[dict[str, Any]]) -> None:
    orders = [criterion["criterion_order"] for criterion in criteria]
    if len(orders) != len(set(orders)):
        raise ValueError("criterion order must be unique per rubric")


def _require_criterion_order_available(
    session: Session,
    rubric_id: str,
    criterion_order: int,
) -> None:
    existing = session.scalar(
        select(RubricCriterion.id).where(
            RubricCriterion.rubric_id == rubric_id,
            RubricCriterion.criterion_order == criterion_order,
        )
    )
    if existing is not None:
        raise ValueError("criterion order must be unique per rubric")
