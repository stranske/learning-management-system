"""Repository helpers for personal capability targets."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from lms.capability.models import CAPABILITY_TARGET_STATUSES, CapabilityTarget
from lms.competencies.models import Competency
from lms.graphs.models import KnowledgeNode
from lms.learners.models import Learner, LearningGoal


def create_capability_target(
    session: Session,
    *,
    learner_id: str,
    title: str,
    ownership_scope: str = "personal",
    description: str | None = None,
    learning_goal_id: str | None = None,
    target_node_ids: list[str] | None = None,
    target_competency_ids: list[str] | None = None,
    required_evidence_types: list[str] | None = None,
    confidence_threshold: float = 0.8,
    status: str = "active",
) -> CapabilityTarget:
    """Create a personal capability target with validated graph and competency links."""
    _require_personal_scope(ownership_scope)
    _require_status(status)
    _require_confidence_threshold(confidence_threshold)
    _require_learner(session, learner_id)
    goal = _load_learning_goal(
        session,
        learner_id=learner_id,
        learning_goal_id=learning_goal_id,
        ownership_scope=ownership_scope,
    )
    target_nodes = _load_target_nodes(
        session,
        target_node_ids=target_node_ids or [],
        ownership_scope=ownership_scope,
        goal=goal,
    )
    target_competencies = _load_target_competencies(
        session,
        target_competency_ids=target_competency_ids or [],
        ownership_scope=ownership_scope,
    )
    if not target_nodes and not target_competencies:
        raise ValueError("capability target requires at least one node or competency")

    target = CapabilityTarget(
        learner_id=learner_id,
        title=title,
        description=description,
        ownership_scope=ownership_scope,
        learning_goal_id=learning_goal_id,
        target_nodes=target_nodes,
        target_competencies=target_competencies,
        required_evidence_types=_normalized_strings(required_evidence_types or []),
        confidence_threshold=confidence_threshold,
        status=status,
    )
    session.add(target)
    session.flush()
    return target


def get_capability_target(session: Session, target_id: str) -> CapabilityTarget | None:
    """Return one capability target by id."""
    return session.get(CapabilityTarget, target_id)


def list_capability_targets(
    session: Session,
    *,
    learner_id: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> Sequence[CapabilityTarget]:
    """List capability targets with optional learner and status filters."""
    statement = select(CapabilityTarget)
    if learner_id is not None:
        statement = statement.where(CapabilityTarget.learner_id == learner_id)
    if status is not None:
        _require_status(status)
        statement = statement.where(CapabilityTarget.status == status)
    statement = statement.order_by(
        CapabilityTarget.created_at.desc(), CapabilityTarget.id
    ).limit(limit)
    return list(session.scalars(statement))


def update_capability_target(
    session: Session,
    target: CapabilityTarget,
    *,
    title: str | None = None,
    description: str | None = None,
    learning_goal_id: str | None = None,
    target_node_ids: list[str] | None = None,
    target_competency_ids: list[str] | None = None,
    required_evidence_types: list[str] | None = None,
    confidence_threshold: float | None = None,
    status: str | None = None,
) -> CapabilityTarget:
    """Update mutable capability target fields."""
    next_status = status if status is not None else target.status
    _require_status(next_status)
    if confidence_threshold is not None:
        _require_confidence_threshold(confidence_threshold)

    next_goal_id = learning_goal_id if learning_goal_id is not None else target.learning_goal_id
    goal = _load_learning_goal(
        session,
        learner_id=target.learner_id,
        learning_goal_id=next_goal_id,
        ownership_scope=target.ownership_scope,
    )
    if title is not None:
        target.title = title
    if description is not None:
        target.description = description
    target.learning_goal_id = next_goal_id
    if target_node_ids is not None:
        target.target_nodes = _load_target_nodes(
            session,
            target_node_ids=target_node_ids,
            ownership_scope=target.ownership_scope,
            goal=goal,
        )
    if target_competency_ids is not None:
        target.target_competencies = _load_target_competencies(
            session,
            target_competency_ids=target_competency_ids,
            ownership_scope=target.ownership_scope,
        )
    if required_evidence_types is not None:
        target.required_evidence_types = _normalized_strings(required_evidence_types)
    if confidence_threshold is not None:
        target.confidence_threshold = confidence_threshold
    target.status = next_status
    if not target.target_nodes and not target.target_competencies:
        raise ValueError("capability target requires at least one node or competency")
    session.flush()
    return target


def archive_capability_target(session: Session, target: CapabilityTarget) -> CapabilityTarget:
    """Archive a target without deleting its planning history."""
    target.status = "archived"
    session.flush()
    return target


def serialize_capability_target(target: CapabilityTarget) -> dict[str, object]:
    """Return a response-ready capability target payload."""
    return {
        "id": target.id,
        "learner_id": target.learner_id,
        "title": target.title,
        "description": target.description,
        "ownership_scope": target.ownership_scope,
        "learning_goal_id": target.learning_goal_id,
        "required_evidence_types": target.required_evidence_types,
        "confidence_threshold": target.confidence_threshold,
        "status": target.status,
        "target_node_ids": [node.id for node in target.target_nodes],
        "target_competency_ids": [competency.id for competency in target.target_competencies],
        "created_at": target.created_at,
        "updated_at": target.updated_at,
    }


def _require_personal_scope(ownership_scope: str) -> None:
    if ownership_scope != "personal":
        raise ValueError("capability targets only support ownership_scope='personal' in M5")


def _require_status(status: str) -> None:
    if status not in CAPABILITY_TARGET_STATUSES:
        raise ValueError(
            f"unknown capability target status {status!r}; expected one of "
            f"{CAPABILITY_TARGET_STATUSES}"
        )


def _require_confidence_threshold(value: float) -> None:
    if not 0.0 <= value <= 1.0:
        raise ValueError("confidence_threshold must be between 0.0 and 1.0")


def _require_learner(session: Session, learner_id: str) -> None:
    if session.get(Learner, learner_id) is None:
        raise ValueError("learner must exist before creating a capability target")


def _load_learning_goal(
    session: Session,
    *,
    learner_id: str,
    learning_goal_id: str | None,
    ownership_scope: str,
) -> LearningGoal | None:
    if learning_goal_id is None:
        return None
    goal = session.get(LearningGoal, learning_goal_id)
    if goal is None or goal.learner_id != learner_id:
        raise ValueError("learning goal must belong to the target learner")
    if goal.ownership_scope != ownership_scope:
        raise ValueError("learning goal ownership_scope must match capability target scope")
    return goal


def _load_target_nodes(
    session: Session,
    *,
    target_node_ids: list[str],
    ownership_scope: str,
    goal: LearningGoal | None,
) -> list[KnowledgeNode]:
    if not target_node_ids:
        return []
    nodes = list(
        session.scalars(
            select(KnowledgeNode).where(
                KnowledgeNode.id.in_(target_node_ids),
                KnowledgeNode.ownership_scope == ownership_scope,
            )
        )
    )
    found_by_id = {node.id: node for node in nodes}
    missing = [node_id for node_id in target_node_ids if node_id not in found_by_id]
    if missing:
        raise ValueError(f"target knowledge nodes not found in this scope: {', '.join(missing)}")
    ordered_nodes = [found_by_id[node_id] for node_id in target_node_ids]
    if goal is not None:
        goal_node_ids = {node.id for node in goal.target_nodes}
        outside_goal = [node.id for node in ordered_nodes if node.id not in goal_node_ids]
        if outside_goal:
            raise ValueError("target nodes must be linked to the learning goal when provided")
    return ordered_nodes


def _load_target_competencies(
    session: Session,
    *,
    target_competency_ids: list[str],
    ownership_scope: str,
) -> list[Competency]:
    if not target_competency_ids:
        return []
    competencies = list(
        session.scalars(
            select(Competency).where(
                Competency.id.in_(target_competency_ids),
                Competency.ownership_scope == ownership_scope,
            )
        )
    )
    found_by_id = {competency.id: competency for competency in competencies}
    missing = [
        competency_id
        for competency_id in target_competency_ids
        if competency_id not in found_by_id
    ]
    if missing:
        raise ValueError(f"target competencies not found in this scope: {', '.join(missing)}")
    return [found_by_id[competency_id] for competency_id in target_competency_ids]


def _normalized_strings(values: list[str]) -> list[str]:
    normalized = [value.strip() for value in values if value.strip()]
    if len(set(normalized)) != len(normalized):
        raise ValueError("required_evidence_types must not contain duplicates")
    return normalized
