"""Repository helpers for durable feedback records and actions."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from itertools import islice
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from lms.evidence.models import Attempt, EvidenceRecord
from lms.feedback.models import (
    FeedbackAction,
    FeedbackRecord,
    FeedbackTemplate,
    Hint,
    HintReveal,
    MisconceptionPattern,
    ModelAnswer,
    ModelAnswerReveal,
    Rubric,
    RubricCriterion,
    RubricScore,
)
from lms.graphs.models import OWNERSHIP_SCOPES, KnowledgeEdge, KnowledgeNode
from lms.prompts.models import Prompt
from lms.prompts.repository import get_prompt


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


def create_misconception_pattern(
    session: Session,
    *,
    pattern_label: str,
    wrong_answer_signature: str,
    diagnosis_text: str,
    ownership_scope: str,
    suggested_feedback_action_type: str,
    target_knowledge_node_id: str | None = None,
    confidence: float | None = None,
) -> MisconceptionPattern:
    """Create a deterministic misconception pattern with explicit scope checks."""
    _require_ownership_scope(ownership_scope)
    if target_knowledge_node_id is not None:
        node = session.get(KnowledgeNode, target_knowledge_node_id)
        if node is None:
            raise ValueError("referenced knowledge node was not found")
        if not _scope_matches_or_has_graph_reference(session, ownership_scope, node):
            raise ValueError(
                "misconception pattern knowledge node must match ownership scope "
                "or have a published graph reference"
            )
    pattern = MisconceptionPattern(
        pattern_label=pattern_label,
        wrong_answer_signature=wrong_answer_signature,
        diagnosis_text=diagnosis_text,
        target_knowledge_node_id=target_knowledge_node_id,
        ownership_scope=ownership_scope,
        confidence=confidence,
        suggested_feedback_action_type=suggested_feedback_action_type,
    )
    session.add(pattern)
    session.flush()
    return pattern


def list_misconception_patterns(
    session: Session,
    *,
    ownership_scope: str | None = None,
    target_knowledge_node_id: str | None = None,
    signature_text: str | None = None,
    limit: int = 100,
) -> Sequence[MisconceptionPattern]:
    """List misconception patterns, optionally matching a learner answer signature."""
    statement = select(MisconceptionPattern)
    if ownership_scope is not None:
        _require_ownership_scope(ownership_scope)
        statement = statement.where(MisconceptionPattern.ownership_scope == ownership_scope)
    if target_knowledge_node_id is not None:
        statement = statement.where(
            or_(
                MisconceptionPattern.target_knowledge_node_id == target_knowledge_node_id,
                MisconceptionPattern.target_knowledge_node_id.is_(None),
            )
        )
    if signature_text is not None:
        needle = signature_text.lower()
        candidates = session.scalars(
            statement.order_by(MisconceptionPattern.created_at.desc()).limit(limit)
        )
        return [
            pattern for pattern in candidates if pattern.wrong_answer_signature.lower() in needle
        ]
    return list(
        session.scalars(
            statement.order_by(
                MisconceptionPattern.created_at.desc(), MisconceptionPattern.id
            ).limit(limit)
        )
    )


def create_feedback_template(
    session: Session,
    *,
    name: str,
    template_body: str,
    placeholder_schema: dict[str, Any] | None,
    feedback_level: str,
    action_type: str,
    ownership_scope: str,
    authoring_actor: str,
    status: str = "draft",
    misconception_pattern_id: str | None = None,
    feedback_action_id: str | None = None,
    knowledge_node_ids: list[str] | None = None,
) -> FeedbackTemplate:
    """Create a reusable feedback template with deterministic validation."""
    _require_ownership_scope(ownership_scope)
    _validate_template_copy(template_body)
    normalized_schema = _normalize_placeholder_schema(placeholder_schema or {})
    _validate_template_placeholders(template_body, normalized_schema)
    _validate_feedback_template_links(
        session,
        ownership_scope=ownership_scope,
        misconception_pattern_id=misconception_pattern_id,
        feedback_action_id=feedback_action_id,
        knowledge_node_ids=knowledge_node_ids or [],
    )
    template = FeedbackTemplate(
        name=name,
        template_body=template_body,
        placeholder_schema=normalized_schema,
        feedback_level=feedback_level,
        action_type=action_type,
        ownership_scope=ownership_scope,
        status=status,
        authoring_actor=authoring_actor,
        misconception_pattern_id=misconception_pattern_id,
        feedback_action_id=feedback_action_id,
        knowledge_node_ids=knowledge_node_ids or [],
    )
    session.add(template)
    session.flush()
    return template


def get_feedback_template(session: Session, template_id: str) -> FeedbackTemplate | None:
    """Return one feedback template by id."""
    return session.get(FeedbackTemplate, template_id)


def list_feedback_templates(
    session: Session,
    *,
    ownership_scope: str | None = None,
    feedback_level: str | None = None,
    action_type: str | None = None,
    status: str | None = None,
    knowledge_node_id: str | None = None,
    limit: int = 100,
) -> Sequence[FeedbackTemplate]:
    """List reusable feedback templates with authoring filters."""
    statement = select(FeedbackTemplate)
    if ownership_scope is not None:
        _require_ownership_scope(ownership_scope)
        statement = statement.where(FeedbackTemplate.ownership_scope == ownership_scope)
    if feedback_level is not None:
        statement = statement.where(FeedbackTemplate.feedback_level == feedback_level)
    if action_type is not None:
        statement = statement.where(FeedbackTemplate.action_type == action_type)
    if status is not None:
        statement = statement.where(FeedbackTemplate.status == status)
    statement = statement.order_by(FeedbackTemplate.created_at.desc(), FeedbackTemplate.id)
    if knowledge_node_id is None:
        return list(session.scalars(statement.limit(limit)))
    matches = (
        template
        for template in session.scalars(statement)
        if knowledge_node_id in template.knowledge_node_ids
    )
    return list(islice(matches, limit))


def archive_feedback_template(
    session: Session,
    template: FeedbackTemplate,
) -> FeedbackTemplate:
    """Archive a feedback template without mutating historic rendered records."""
    template.status = "archived"
    session.flush()
    return template


def render_feedback_template(
    template: FeedbackTemplate,
    values: dict[str, Any],
) -> str:
    """Render a template after checking required placeholders are present."""
    required = _required_placeholders(template.placeholder_schema)
    missing = sorted(name for name in required if values.get(name) in (None, ""))
    if missing:
        raise ValueError(f"missing required placeholder values: {', '.join(missing)}")
    try:
        return template.template_body.format(**{key: str(value) for key, value in values.items()})
    except KeyError as exc:
        missing_key = str(exc).strip("'")
        raise ValueError(f"missing placeholder values: {missing_key}") from exc


def create_hint(
    session: Session,
    *,
    prompt_id: str,
    hint_text: str,
    reveal_order: int,
    authoring_actor: str,
    support_level: str = "hint",
    reveal_policy: str = "after-attempt",
    source_citation_metadata: dict[str, Any] | None = None,
) -> Hint:
    """Create one ordered hint for a prompt."""
    if session.get(Prompt, prompt_id) is None:
        raise ValueError("referenced prompt was not found")
    hint = Hint(
        prompt_id=prompt_id,
        hint_text=hint_text,
        reveal_order=reveal_order,
        support_level=support_level,
        reveal_policy=reveal_policy,
        source_citation_metadata=source_citation_metadata,
        authoring_actor=authoring_actor,
    )
    session.add(hint)
    session.flush()
    return hint


def get_hint(session: Session, hint_id: str) -> Hint | None:
    """Return one hint by id."""
    return session.get(Hint, hint_id)


def list_hints(
    session: Session,
    *,
    prompt_id: str | None = None,
    limit: int = 100,
) -> Sequence[Hint]:
    """List hints ordered for learner reveal."""
    statement = select(Hint)
    if prompt_id is not None:
        statement = statement.where(Hint.prompt_id == prompt_id)
    statement = statement.order_by(Hint.prompt_id, Hint.reveal_order, Hint.id).limit(limit)
    return list(session.scalars(statement))


def reveal_hint(
    session: Session,
    hint: Hint,
    *,
    learner_id: str,
    attempt_id: str | None = None,
    initiated_by: str = "learner",
) -> HintReveal:
    """Record a hint reveal and mark related support-sensitive evidence."""
    attempt: Attempt | None = None
    if attempt_id is not None:
        attempt = session.get(Attempt, attempt_id)
        if attempt is None:
            raise ValueError("referenced attempt was not found")
        if attempt.prompt_id != hint.prompt_id:
            raise ValueError("attempt does not match the hint prompt")
        if attempt.learner_id != learner_id:
            raise ValueError("attempt does not match learner")
        attempt.hint_used = True
        attempt.support_level = _stronger_support_level(attempt.support_level, hint.support_level)
        _mark_attempt_evidence_hint_used(session, attempt, hint.support_level)
    reveal = HintReveal(
        hint_id=hint.id,
        learner_id=learner_id,
        prompt_id=hint.prompt_id,
        attempt_id=attempt_id,
        initiated_by=initiated_by,
    )
    session.add(reveal)
    session.flush()
    return reveal


def create_model_answer(
    session: Session,
    *,
    prompt_id: str,
    answer_body: str,
    authoring_actor: str,
    rubric_id: str | None = None,
    reveal_policy: str = "after-attempt",
    source_citation_metadata: dict[str, Any] | None = None,
) -> ModelAnswer:
    """Create one model answer for a prompt."""
    if session.get(Prompt, prompt_id) is None:
        raise ValueError("referenced prompt was not found")
    if rubric_id is not None and session.get(Rubric, rubric_id) is None:
        raise ValueError("referenced rubric was not found")
    answer = ModelAnswer(
        prompt_id=prompt_id,
        rubric_id=rubric_id,
        answer_body=answer_body,
        reveal_policy=reveal_policy,
        source_citation_metadata=source_citation_metadata,
        authoring_actor=authoring_actor,
    )
    session.add(answer)
    session.flush()
    return answer


def get_model_answer(session: Session, model_answer_id: str) -> ModelAnswer | None:
    """Return one model answer by id."""
    return session.get(ModelAnswer, model_answer_id)


def list_model_answers(
    session: Session,
    *,
    prompt_id: str | None = None,
    limit: int = 100,
) -> Sequence[ModelAnswer]:
    """List model answer metadata without implying learner reveal."""
    statement = select(ModelAnswer)
    if prompt_id is not None:
        statement = statement.where(ModelAnswer.prompt_id == prompt_id)
    statement = statement.order_by(ModelAnswer.created_at.desc(), ModelAnswer.id).limit(limit)
    return list(session.scalars(statement))


def reveal_model_answer(
    session: Session,
    model_answer: ModelAnswer,
    *,
    learner_id: str,
    attempt_id: str | None = None,
    initiated_by: str = "learner",
    instructor_mode: bool = False,
) -> ModelAnswerReveal:
    """Record a model-answer reveal after attempt or explicit instructor/test mode."""
    attempt: Attempt | None = None
    if attempt_id is not None:
        attempt = session.get(Attempt, attempt_id)
        if attempt is None:
            raise ValueError("referenced attempt was not found")
        if attempt.prompt_id != model_answer.prompt_id:
            raise ValueError("attempt does not match the model answer prompt")
        if attempt.learner_id != learner_id:
            raise ValueError("attempt does not match learner")
    if model_answer.reveal_policy == "after-attempt" and attempt is None and not instructor_mode:
        raise ValueError("model answer reveal requires a completed attempt")
    if model_answer.reveal_policy == "instructor-only" and not instructor_mode:
        raise ValueError("model answer reveal requires instructor mode")
    reveal = ModelAnswerReveal(
        model_answer_id=model_answer.id,
        learner_id=learner_id,
        prompt_id=model_answer.prompt_id,
        attempt_id=attempt_id,
        initiated_by=initiated_by,
    )
    session.add(reveal)
    session.flush()
    return reveal


def learner_safe_source_citations(
    session: Session,
    prompt_id: str,
    explicit_metadata: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return public prompt citations without exposing local-only locators."""
    prompt = get_prompt(session, prompt_id)
    citations: list[dict[str, Any]] = []
    if prompt is not None:
        for reference in prompt.source_references:
            citation: dict[str, Any] = {
                "source_type": reference.source_type,
                "passage_range": reference.passage_range,
                "source_visibility": reference.source_visibility,
                "stable_locator": None,
            }
            if reference.source_visibility == "public":
                citation["stable_locator"] = reference.stable_locator
            citations.append(citation)
    if explicit_metadata:
        citations.append(
            {
                "source_type": str(explicit_metadata.get("source_type", "metadata")),
                "passage_range": explicit_metadata.get("passage_range"),
                "source_visibility": str(explicit_metadata.get("source_visibility", "public")),
                "stable_locator": explicit_metadata.get("stable_locator"),
            }
        )
    return citations


_SUPPORT_RANK = {
    "none": 0,
    "hint": 1,
    "reference": 2,
    "worked-example": 3,
    "coach": 4,
}


def _stronger_support_level(current: str | None, candidate: str) -> str:
    current_level = current or "none"
    return (
        candidate
        if _SUPPORT_RANK[candidate] > _SUPPORT_RANK.get(current_level, 0)
        else current_level
    )


def _mark_attempt_evidence_hint_used(
    session: Session,
    attempt: Attempt,
    support_level: str,
) -> None:
    records = session.scalars(select(EvidenceRecord).where(EvidenceRecord.attempt_id == attempt.id))
    for record in records:
        record.hint_used = True
        record.support_level = _stronger_support_level(record.support_level, support_level)


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


def _validate_feedback_template_links(
    session: Session,
    *,
    ownership_scope: str,
    misconception_pattern_id: str | None,
    feedback_action_id: str | None,
    knowledge_node_ids: list[str],
) -> None:
    if misconception_pattern_id is not None:
        pattern = session.get(MisconceptionPattern, misconception_pattern_id)
        if pattern is None:
            raise ValueError("referenced misconception pattern was not found")
        if pattern.ownership_scope != ownership_scope:
            raise ValueError("feedback template pattern must match ownership scope")
    if feedback_action_id is not None and session.get(FeedbackAction, feedback_action_id) is None:
        raise ValueError("referenced feedback action was not found")
    for node_id in knowledge_node_ids:
        node = session.get(KnowledgeNode, node_id)
        if node is None:
            raise ValueError("referenced knowledge node was not found")
        if not _scope_matches_or_has_graph_reference(session, ownership_scope, node):
            raise ValueError(
                "feedback template knowledge nodes must match ownership scope "
                "or have a published graph reference"
            )


def _normalize_placeholder_schema(schema: dict[str, Any]) -> dict[str, Any]:
    required = schema.get("required", [])
    if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
        raise ValueError("placeholder_schema.required must be a list of strings")
    return {**schema, "required": sorted(set(required))}


def _validate_template_placeholders(template_body: str, schema: dict[str, Any]) -> None:
    missing_from_body = sorted(
        placeholder
        for placeholder in _required_placeholders(schema)
        if f"{{{placeholder}}}" not in template_body
    )
    if missing_from_body:
        raise ValueError(
            "template_body must include required placeholders: " + ", ".join(missing_from_body)
        )


def _required_placeholders(schema: dict[str, Any]) -> list[str]:
    required = schema.get("required", [])
    return [item for item in required if isinstance(item, str)]


def _validate_template_copy(template_body: str) -> None:
    lower_body = template_body.lower()
    fixed_label_phrases = (
        "low ability",
        "high ability",
        "not a math person",
        "naturally smart",
        "lazy learner",
        "weak student",
    )
    for phrase in fixed_label_phrases:
        if phrase in lower_body:
            raise ValueError("feedback template copy must avoid fixed ability labels")


def _scope_matches_or_has_graph_reference(
    session: Session, ownership_scope: str, node: KnowledgeNode
) -> bool:
    if node.ownership_scope == ownership_scope:
        return True
    statement = (
        select(KnowledgeEdge.id)
        .where(
            KnowledgeEdge.target_node_id == node.id,
            KnowledgeEdge.source_scope == ownership_scope,
            KnowledgeEdge.target_scope == node.ownership_scope,
            KnowledgeEdge.is_graph_reference.is_(True),
            KnowledgeEdge.status == "published",
        )
        .limit(1)
    )
    return session.scalar(statement) is not None


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
