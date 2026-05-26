"""Repository helpers for prompt authoring and publication."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from lms.audit.repository import record_audit_event
from lms.graphs.models import KNOWLEDGE_TYPES
from lms.graphs.repository import require_published_prompt_target
from lms.learners.models import LearningGoal
from lms.prompts.models import (
    ANSWER_FORMS,
    AUTHORING_METHODS,
    COGNITIVE_ACTIONS,
    DEMAND_LEVELS,
    PROMPT_STATUSES,
    Prompt,
    PromptVersion,
)
from lms.sources.models import SourceReference


def create_prompt(
    session: Session,
    *,
    target_node_id: str,
    learning_goal_id: str,
    knowledge_type: str,
    intended_cognitive_action: str,
    demand_level: str,
    expected_answer_form: str,
    body: str,
    source_reference_ids: list[str],
    authoring_method: str,
    authoring_actor: str,
    llm_model: str | None = None,
    prompt_template_version: str | None = None,
    status: str | None = None,
    source_subsystem: str = "api",
) -> Prompt:
    """Create a prompt, initial version, source links, and audit event."""
    _require_choice(knowledge_type, KNOWLEDGE_TYPES, "knowledge type")
    _require_choice(intended_cognitive_action, COGNITIVE_ACTIONS, "cognitive action")
    _require_choice(demand_level, DEMAND_LEVELS, "demand level")
    _require_choice(expected_answer_form, ANSWER_FORMS, "expected answer form")
    _require_choice(authoring_method, AUTHORING_METHODS, "authoring method")

    goal = _get_goal(session, learning_goal_id)
    target_node = require_published_prompt_target(
        session,
        node_id=target_node_id,
        scope=goal.ownership_scope,
    )
    if goal.ownership_scope != target_node.ownership_scope:
        raise ValueError("prompt target node must match the learning goal scope")
    if target_node.id not in {node.id for node in goal.target_nodes}:
        raise ValueError("prompt target node must be linked to the learning goal")

    references = _load_source_references(session, source_reference_ids)
    resolved_status = status or "draft"
    if authoring_method == "llm-generated" and resolved_status != "draft":
        raise ValueError("llm-generated prompts must start as draft until human review")
    _require_choice(resolved_status, PROMPT_STATUSES, "prompt status")
    if resolved_status == "published":
        raise ValueError("new prompts must be published through the review endpoint")

    prompt = Prompt(
        target_node_id=target_node_id,
        learning_goal_id=learning_goal_id,
        knowledge_type=knowledge_type,
        intended_cognitive_action=intended_cognitive_action,
        demand_level=demand_level,
        expected_answer_form=expected_answer_form,
        status=resolved_status,
        authoring_method=authoring_method,
        authoring_actor=authoring_actor,
        llm_model=llm_model,
        prompt_template_version=prompt_template_version,
        source_references=references,
    )
    prompt.versions.append(PromptVersion(version_number=1, body=body, created_by=authoring_actor))
    session.add(prompt)
    session.flush()
    record_audit_event(
        session,
        actor_id=authoring_actor,
        action="create",
        entity_type="Prompt",
        entity_id=prompt.id,
        source_subsystem=source_subsystem,
        after_summary=_prompt_summary(prompt),
    )
    return prompt


def get_prompt(session: Session, prompt_id: str) -> Prompt | None:
    """Return a prompt by stable id."""
    return session.scalar(
        select(Prompt)
        .options(selectinload(Prompt.source_references), selectinload(Prompt.versions))
        .where(Prompt.id == prompt_id)
    )


def list_prompts(
    session: Session,
    *,
    status: str | None = None,
    learning_goal_id: str | None = None,
    limit: int = 100,
) -> Sequence[Prompt]:
    """List prompts with optional publication or goal filters."""
    statement = select(Prompt).options(
        selectinload(Prompt.source_references),
        selectinload(Prompt.versions),
    )
    if status is not None:
        _require_choice(status, PROMPT_STATUSES, "prompt status")
        statement = statement.where(Prompt.status == status)
    if learning_goal_id is not None:
        statement = statement.where(Prompt.learning_goal_id == learning_goal_id)
    statement = statement.order_by(Prompt.created_at.desc(), Prompt.id).limit(limit)
    return list(session.scalars(statement))


def version_prompt(
    session: Session,
    prompt: Prompt,
    *,
    body: str,
    actor_id: str,
    source_subsystem: str = "api",
    **changes: Any,
) -> Prompt:
    """Update prompt metadata and append a new immutable wording version."""
    before = _prompt_summary(prompt)
    _apply_prompt_changes(prompt, changes)
    next_version = (
        session.scalar(
            select(func.max(PromptVersion.version_number)).where(
                PromptVersion.prompt_id == prompt.id
            )
        )
        or 0
    ) + 1
    prompt.versions.append(
        PromptVersion(version_number=next_version, body=body, created_by=actor_id)
    )
    if prompt.status == "published":
        prompt.status = "in-review"
        prompt.reviewing_actor = None
        prompt.approval_timestamp = None
    session.flush()
    record_audit_event(
        session,
        actor_id=actor_id,
        action="version",
        entity_type="Prompt",
        entity_id=prompt.id,
        source_subsystem=source_subsystem,
        before_summary=before,
        after_summary=_prompt_summary(prompt),
    )
    return prompt


def require_publishable_prompt(prompt: Prompt) -> Prompt:
    """Return the prompt only if it can be surfaced to learners.

    The scheduler and any other learner-facing delivery path must call this
    before exposing a prompt: it refuses draft / in-review / archived prompts
    so LLM-generated proposals cannot reach a learner before a human reviewer
    approves them. The check is intentionally minimal — the trust boundary is
    the ``status`` column, set to ``published`` only through
    :func:`publish_prompt`.
    """
    if prompt.status != "published":
        raise ValueError(
            f"prompt {prompt.id!r} is not publishable for scheduler use: "
            f"status={prompt.status!r}, authoring_method={prompt.authoring_method!r}"
        )
    return prompt


def publish_prompt(
    session: Session,
    prompt: Prompt,
    *,
    reviewing_actor: str,
    approval_timestamp: datetime | None = None,
    source_subsystem: str = "api",
) -> Prompt:
    """Mark a reviewed prompt as published and record provenance."""
    if not prompt.source_references:
        raise ValueError("prompt requires at least one source reference before publication")
    before = _prompt_summary(prompt)
    prompt.status = "published"
    prompt.reviewing_actor = reviewing_actor
    prompt.approval_timestamp = approval_timestamp or datetime.now(UTC)
    session.flush()
    record_audit_event(
        session,
        actor_id=reviewing_actor,
        action="publish",
        entity_type="Prompt",
        entity_id=prompt.id,
        source_subsystem=source_subsystem,
        before_summary=before,
        after_summary=_prompt_summary(prompt),
    )
    return prompt


def _get_goal(session: Session, learning_goal_id: str) -> LearningGoal:
    goal = session.get(LearningGoal, learning_goal_id)
    if goal is None:
        raise ValueError("learning goal must exist before creating a prompt")
    return goal


def _load_source_references(
    session: Session,
    source_reference_ids: list[str],
) -> list[SourceReference]:
    if not source_reference_ids:
        raise ValueError("prompt requires at least one source reference")
    references = list(
        session.scalars(select(SourceReference).where(SourceReference.id.in_(source_reference_ids)))
    )
    found_by_id = {reference.id: reference for reference in references}
    missing = [
        reference_id for reference_id in source_reference_ids if reference_id not in found_by_id
    ]
    if missing:
        raise ValueError(f"source references not found: {', '.join(missing)}")
    return [found_by_id[reference_id] for reference_id in source_reference_ids]


def _apply_prompt_changes(prompt: Prompt, changes: dict[str, Any]) -> None:
    for field, value in changes.items():
        if value is None:
            continue
        if field == "knowledge_type":
            _require_choice(value, KNOWLEDGE_TYPES, "knowledge type")
        elif field == "intended_cognitive_action":
            _require_choice(value, COGNITIVE_ACTIONS, "cognitive action")
        elif field == "demand_level":
            _require_choice(value, DEMAND_LEVELS, "demand level")
        elif field == "expected_answer_form":
            _require_choice(value, ANSWER_FORMS, "expected answer form")
        elif field == "status":
            _require_choice(value, PROMPT_STATUSES, "prompt status")
            if value == "published":
                raise ValueError("use publish_prompt to publish reviewed prompts")
        setattr(prompt, field, value)


def _require_choice(value: str, allowed: tuple[str, ...], label: str) -> None:
    if value not in allowed:
        raise ValueError(f"unknown {label} {value!r}; expected one of {allowed}")


def _prompt_summary(prompt: Prompt) -> dict[str, Any]:
    return {
        "id": prompt.id,
        "target_node_id": prompt.target_node_id,
        "learning_goal_id": prompt.learning_goal_id,
        "knowledge_type": prompt.knowledge_type,
        "intended_cognitive_action": prompt.intended_cognitive_action,
        "demand_level": prompt.demand_level,
        "expected_answer_form": prompt.expected_answer_form,
        "status": prompt.status,
        "authoring_method": prompt.authoring_method,
        "authoring_actor": prompt.authoring_actor,
        "reviewing_actor": prompt.reviewing_actor,
        "approval_timestamp": (
            prompt.approval_timestamp.isoformat() if prompt.approval_timestamp is not None else None
        ),
        "llm_model": prompt.llm_model,
        "prompt_template_version": prompt.prompt_template_version,
        "source_reference_ids": [reference.id for reference in prompt.source_references],
        "version_count": len(prompt.versions),
    }
