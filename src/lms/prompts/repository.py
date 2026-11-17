"""Repository helpers for prompt authoring and publication."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
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
    PROMPT_DRIFT_STATUSES,
    PROMPT_STATUSES,
    Prompt,
    PromptDriftAcknowledgement,
    PromptVersion,
    PromptVersionSourceSnapshot,
)
from lms.sources.models import SourceReference
from lms.sources.repository import compute_source_hash_for_reference

logger = logging.getLogger(__name__)

_PROMPT_DRIFT_RANK = {status: index for index, status in enumerate(PROMPT_DRIFT_STATUSES)}


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
    initial_version = PromptVersion(
        version_number=1,
        body=body,
        created_by=authoring_actor,
        task_context=_prompt_task_context(prompt),
    )
    prompt.versions.append(initial_version)
    session.add(prompt)
    session.flush()
    _capture_version_source_snapshots(initial_version, references)
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
        .options(
            selectinload(Prompt.source_references),
            selectinload(Prompt.drift_acknowledgements),
            selectinload(Prompt.versions).selectinload(PromptVersion.source_snapshots),
        )
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
        selectinload(Prompt.drift_acknowledgements),
        selectinload(Prompt.versions).selectinload(PromptVersion.source_snapshots),
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
    _preserve_outgoing_version_context(session, prompt)
    _apply_prompt_changes(prompt, changes)
    next_version = (
        session.scalar(
            select(func.max(PromptVersion.version_number)).where(
                PromptVersion.prompt_id == prompt.id
            )
        )
        or 0
    ) + 1
    version = PromptVersion(
        version_number=next_version,
        body=body,
        created_by=actor_id,
        task_context=_prompt_task_context(prompt),
    )
    prompt.versions.append(version)
    if prompt.status == "published":
        prompt.status = "in-review"
        prompt.reviewing_actor = None
        prompt.approval_timestamp = None
    session.flush()
    _capture_version_source_snapshots(version, prompt.source_references)
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


def prompt_drift_status(prompt: Prompt, *, base_path: str | Path | None = None) -> str:
    """Return prompt-level drift from version snapshots and source scan state."""
    if not prompt.versions or not prompt.source_references:
        return "current"
    latest_version = prompt.versions[-1]
    acknowledgement = next(
        (
            ack
            for ack in reversed(prompt.drift_acknowledgements)
            if ack.prompt_version_id == latest_version.id
        ),
        None,
    )
    snapshots = {
        snapshot.source_reference_id: snapshot for snapshot in latest_version.source_snapshots
    }
    per_source = [
        (
            "current"
            if _is_source_drift_acknowledged(reference, acknowledgement, base_path=base_path)
            else _source_drift_for_reference(reference, snapshots.get(reference.id))
        )
        for reference in prompt.source_references
    ]
    return max(per_source, key=lambda status: _PROMPT_DRIFT_RANK[status])


def acknowledge_prompt_drift(
    session: Session,
    prompt: Prompt,
    *,
    actor_id: str,
    prompt_version_id: str | None = None,
    source_subsystem: str = "api",
    reviewed_source_states: dict[str, dict[str, Any]] | None = None,
    base_path: str | Path | None = None,
) -> PromptDriftAcknowledgement:
    """Record that an author reviewed prompt-level source drift for one version."""
    if not prompt.versions:
        raise ValueError("prompt has no versions to acknowledge")
    version_id = prompt_version_id or prompt.versions[-1].id
    if not any(version.id == version_id for version in prompt.versions):
        raise ValueError("prompt_version_id does not belong to prompt")
    reviewed_states = (
        capture_prompt_source_states(prompt, base_path=base_path)
        if reviewed_source_states is None
        else deepcopy(reviewed_source_states)
    )
    existing = next(
        (ack for ack in prompt.drift_acknowledgements if ack.prompt_version_id == version_id),
        None,
    )
    if existing is not None:
        existing.acknowledged_by = actor_id
        existing.acknowledged_at = datetime.now(UTC)
        existing.acknowledged_source_states = reviewed_states
        acknowledgement = existing
    else:
        acknowledgement = PromptDriftAcknowledgement(
            prompt_id=prompt.id,
            prompt_version_id=version_id,
            acknowledged_by=actor_id,
            acknowledged_source_states=reviewed_states,
        )
        prompt.drift_acknowledgements.append(acknowledgement)
    session.flush()
    record_audit_event(
        session,
        actor_id=actor_id,
        action="acknowledge-drift",
        entity_type="Prompt",
        entity_id=prompt.id,
        source_subsystem=source_subsystem,
        after_summary={
            "prompt_id": prompt.id,
            "prompt_version_id": version_id,
            "acknowledged_by": actor_id,
            "acknowledged_source_states": reviewed_states,
        },
    )
    return acknowledgement


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


def _capture_version_source_snapshots(
    version: PromptVersion,
    references: Sequence[SourceReference],
) -> None:
    """Persist immutable source hashes for one prompt version."""
    for reference in references:
        version.source_snapshots.append(
            PromptVersionSourceSnapshot(
                source_reference_id=reference.id,
                content_hash=reference.content_hash,
                hash_algorithm=reference.hash_algorithm,
            )
        )


def _resolved_markdown_hash(
    reference: SourceReference, *, base_path: str | Path | None = None
) -> str | None:
    if reference.source_type != "markdown-file":
        return None
    try:
        return compute_source_hash_for_reference(
            source_type=reference.source_type,
            stable_locator=reference.stable_locator,
            passage_range=reference.passage_range,
            content=None,
            hash_algorithm=reference.hash_algorithm,
            base_path=base_path,
        )
    except (FileNotFoundError, OSError, ValueError) as exc:
        logger.warning(
            "unable to resolve markdown hash for source reference %s at %s: %s",
            reference.id,
            reference.stable_locator,
            exc,
        )
        return None


def _capture_acknowledged_source_states(
    references: Sequence[SourceReference],
    *,
    base_path: str | Path | None = None,
) -> dict[str, dict[str, Any]]:
    """Snapshot the reviewed state of each linked source reference."""
    states: dict[str, dict[str, Any]] = {}
    for reference in references:
        state: dict[str, Any] = {
            "content_hash": reference.content_hash,
            "hash_algorithm": reference.hash_algorithm,
            "drift_status": reference.drift_status,
        }
        resolved_hash = _resolved_markdown_hash(reference, base_path=base_path)
        if resolved_hash is not None:
            state["resolved_content_hash"] = resolved_hash
        states[reference.id] = state
    return states


def capture_prompt_source_states(
    prompt: Prompt, *, base_path: str | Path | None = None
) -> dict[str, dict[str, Any]]:
    """Capture the source state shown for drift acknowledgement."""
    return _capture_acknowledged_source_states(prompt.source_references, base_path=base_path)


def source_state_digest(states: Mapping[str, Mapping[str, Any]]) -> str:
    """Return a stable digest of captured source states."""
    payload = {reference_id: dict(state) for reference_id, state in states.items()}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def prompt_source_state_digest(prompt: Prompt, *, base_path: str | Path | None = None) -> str:
    """Return a stable digest of the source state shown for drift acknowledgement."""
    return source_state_digest(capture_prompt_source_states(prompt, base_path=base_path))


def _is_source_drift_acknowledged(
    reference: SourceReference,
    acknowledgement: PromptDriftAcknowledgement | None,
    *,
    base_path: str | Path | None = None,
) -> bool:
    if acknowledgement is None:
        return False
    acknowledged_states = acknowledgement.acknowledged_source_states or {}
    state = acknowledged_states.get(reference.id)
    if not isinstance(state, dict):
        return False
    if (
        state.get("content_hash") != reference.content_hash
        or state.get("hash_algorithm") != reference.hash_algorithm
        or state.get("drift_status") != reference.drift_status
    ):
        return False
    if reference.drift_status == "stale" and "resolved_content_hash" in state:
        current_resolved_hash = _resolved_markdown_hash(reference, base_path=base_path)
        if current_resolved_hash is None or current_resolved_hash != state["resolved_content_hash"]:
            return False
    return True


def _source_drift_for_reference(
    reference: SourceReference,
    snapshot: PromptVersionSourceSnapshot | None,
) -> str:
    if reference.drift_status == "missing":
        return "missing"
    if reference.drift_status == "stale":
        return "stale"
    if snapshot is None:
        return "unknown"
    if (
        snapshot.content_hash != reference.content_hash
        or snapshot.hash_algorithm != reference.hash_algorithm
    ):
        return "stale"
    return "current"


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


def _prompt_task_context(prompt: Prompt) -> dict[str, Any]:
    return {
        "target_node_id": prompt.target_node_id,
        "learning_goal_id": prompt.learning_goal_id,
        "knowledge_type": prompt.knowledge_type,
        "demand_level": prompt.demand_level,
        "intended_cognitive_action": prompt.intended_cognitive_action,
        "expected_answer_form": prompt.expected_answer_form,
        "source_reference_ids": [source.id for source in prompt.source_references],
    }


def _preserve_outgoing_version_context(session: Session, prompt: Prompt) -> None:
    """Freeze task metadata on the current version before prompt-level edits."""
    latest_version = session.scalar(
        select(PromptVersion)
        .where(PromptVersion.prompt_id == prompt.id)
        .order_by(PromptVersion.version_number.desc())
        .limit(1)
    )
    if latest_version is not None and latest_version.task_context is None:
        latest_version.task_context = _prompt_task_context(prompt)


def version_task_context(version: PromptVersion) -> dict[str, Any] | None:
    """Return a copied task snapshot for a version when one was recorded."""
    if version.task_context is None:
        return None
    return deepcopy(version.task_context)


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
