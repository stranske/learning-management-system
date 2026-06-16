"""Repository helpers for learner profiles."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from lms.evidence.models import EvidenceRecord
from lms.graphs.models import KNOWLEDGE_TYPES, OWNERSHIP_SCOPES, KnowledgeNode
from lms.learners.models import (
    GOAL_STATUSES,
    MASTERY_THRESHOLD,
    Learner,
    LearnerReflection,
    LearningGoal,
)
from lms.mastery.service import (
    mastery_estimates_for_learner,
    mastery_estimates_with_evidence_for_learner,
)

TRANSFER_EVIDENCE_DISTANCES: tuple[str, ...] = ("near", "far", "novel", "case-transfer")


def create_learner_for_user(
    session: Session,
    *,
    user_id: str,
    display_name: str,
    timezone: str = "UTC",
    locale: str = "en-US",
) -> Learner:
    """Create a learner profile for an explicit user id."""
    learner = Learner(
        user_id=user_id,
        display_name=display_name,
        timezone=timezone,
        locale=locale,
    )
    session.add(learner)
    session.flush()
    return learner


def get_learner(session: Session, *, learner_id: str) -> Learner | None:
    """Return a learner by explicit learner id."""
    return session.get(Learner, learner_id)


def list_learners_for_user(session: Session, *, user_id: str) -> list[Learner]:
    """Return learner profiles for an explicit user id."""
    return list(session.scalars(select(Learner).where(Learner.user_id == user_id)))


def create_learning_goal(
    session: Session,
    *,
    learner_id: str,
    title: str,
    knowledge_type: str,
    target_node_ids: list[str],
    ownership_scope: str,
    status: str = "active",
) -> LearningGoal:
    """Create a learner goal tied only to published nodes in one scope."""
    _require_learning_goal_choices(
        knowledge_type=knowledge_type,
        ownership_scope=ownership_scope,
        status=status,
    )
    learner = get_learner(session, learner_id=learner_id)
    if learner is None:
        raise ValueError("learner must exist before creating a learning goal")

    target_nodes = _load_goal_target_nodes(
        session,
        target_node_ids=target_node_ids,
        ownership_scope=ownership_scope,
    )
    goal = LearningGoal(
        learner_id=learner_id,
        title=title,
        knowledge_type=knowledge_type,
        ownership_scope=ownership_scope,
        status=status,
        target_nodes=target_nodes,
    )
    session.add(goal)
    session.flush()
    return goal


def update_learning_goal(
    session: Session,
    goal: LearningGoal,
    *,
    title: str | None = None,
    knowledge_type: str | None = None,
    target_node_ids: list[str] | None = None,
    ownership_scope: str | None = None,
    status: str | None = None,
) -> LearningGoal:
    """Update mutable goal fields and retarget nodes when requested."""
    next_knowledge_type = knowledge_type if knowledge_type is not None else goal.knowledge_type
    next_ownership_scope = ownership_scope if ownership_scope is not None else goal.ownership_scope
    next_status = status if status is not None else goal.status
    _require_learning_goal_choices(
        knowledge_type=next_knowledge_type,
        ownership_scope=next_ownership_scope,
        status=next_status,
    )

    if title is not None:
        goal.title = title
    goal.knowledge_type = next_knowledge_type
    goal.ownership_scope = next_ownership_scope
    goal.status = next_status
    if target_node_ids is not None:
        goal.target_nodes = _load_goal_target_nodes(
            session,
            target_node_ids=target_node_ids,
            ownership_scope=next_ownership_scope,
        )
    session.flush()
    return goal


def get_learning_goal(
    session: Session,
    *,
    learner_id: str,
    goal_id: str,
) -> LearningGoal | None:
    """Return one goal for a learner."""
    statement = select(LearningGoal).where(
        LearningGoal.id == goal_id,
        LearningGoal.learner_id == learner_id,
    )
    return session.scalars(statement).one_or_none()


def list_learning_goals_for_learner(
    session: Session,
    *,
    learner_id: str,
    ownership_scope: str | None = None,
    status: str | None = None,
) -> list[LearningGoal]:
    """Return learning goals for one learner, optionally filtered."""
    statement = select(LearningGoal).where(LearningGoal.learner_id == learner_id)
    if ownership_scope is not None:
        _require_ownership_scope(ownership_scope)
        statement = statement.where(LearningGoal.ownership_scope == ownership_scope)
    if status is not None:
        if status not in GOAL_STATUSES:
            raise ValueError(f"unknown goal status {status!r}; expected one of {GOAL_STATUSES}")
        statement = statement.where(LearningGoal.status == status)
    statement = statement.order_by(LearningGoal.created_at.desc(), LearningGoal.id)
    return list(session.scalars(statement))


def knowledge_profile_for_learner(
    session: Session,
    *,
    learner_id: str,
    ownership_scope: str = "personal",
) -> dict[str, object]:
    """Return a computed learner knowledge profile for one ownership scope."""
    _require_ownership_scope(ownership_scope)

    estimates, evidence_by_estimate_node = mastery_estimates_with_evidence_for_learner(
        session,
        learner_id,
    )
    if not estimates:
        return {"learner_id": learner_id, "ownership_scope": ownership_scope, "items": []}

    node_ids = [str(estimate["knowledge_node_id"]) for estimate in estimates]
    nodes = {
        node.id: node
        for node in session.scalars(
            select(KnowledgeNode).where(
                KnowledgeNode.id.in_(node_ids),
                KnowledgeNode.ownership_scope == ownership_scope,
            )
        )
    }
    if not nodes:
        return {"learner_id": learner_id, "ownership_scope": ownership_scope, "items": []}

    evidence_by_node: dict[str, list[EvidenceRecord]] = {
        node_id: evidence_by_estimate_node.get(node_id, []) for node_id in nodes
    }

    items: list[dict[str, object]] = []
    for estimate in estimates:
        node_id = str(estimate["knowledge_node_id"])
        node = nodes.get(node_id)
        if node is None:
            continue
        records = evidence_by_node.get(node_id, [])
        markers = _support_dependence_markers(records)
        has_transfer_evidence = _has_transfer_evidence(records)
        items.append(
            {
                "learner_id": learner_id,
                "ownership_scope": ownership_scope,
                "knowledge_node_id": node_id,
                "knowledge_node_title": node.title,
                "knowledge_type": node.knowledge_type,
                "current_estimate": estimate["current_estimate"],
                "confidence": estimate["confidence"],
                "evidence_count": estimate["evidence_count"],
                "last_evidence_id": estimate["last_evidence_id"],
                "support_dependence_markers": markers,
                "has_transfer_evidence": has_transfer_evidence,
                "next_evidence_needed": _next_evidence_needed(
                    current_estimate=float(estimate["current_estimate"]),
                    confidence=float(estimate["confidence"]),
                    markers=markers,
                    has_transfer_evidence=has_transfer_evidence,
                ),
                "generated_at": estimate["generated_at"],
            }
        )
    items.sort(
        key=lambda item: (str(item["knowledge_node_title"]).lower(), item["knowledge_node_id"])
    )
    return {"learner_id": learner_id, "ownership_scope": ownership_scope, "items": items}


def create_reflection(
    session: Session,
    *,
    learner_id: str,
    prompt: str,
    response: str,
    knowledge_node_id: str | None = None,
) -> LearnerReflection:
    """Persist a learner's metacognitive reflection after a review."""
    if get_learner(session, learner_id=learner_id) is None:
        raise ValueError("learner must exist before recording a reflection")
    if not prompt.strip():
        raise ValueError("reflection prompt must not be empty")
    if not response.strip():
        raise ValueError("reflection response must not be empty")
    if knowledge_node_id is not None and session.get(KnowledgeNode, knowledge_node_id) is None:
        raise ValueError(f"knowledge node not found: {knowledge_node_id}")

    reflection = LearnerReflection(
        learner_id=learner_id,
        prompt=prompt,
        response=response,
        knowledge_node_id=knowledge_node_id,
    )
    session.add(reflection)
    session.flush()
    return reflection


def list_reflections_for_learner(
    session: Session,
    *,
    learner_id: str,
    limit: int | None = None,
) -> list[LearnerReflection]:
    """Return a learner's reflections, newest first (the learner-facing surface)."""
    statement = (
        select(LearnerReflection)
        .where(LearnerReflection.learner_id == learner_id)
        .order_by(LearnerReflection.created_at.desc(), LearnerReflection.id)
    )
    if limit is not None:
        statement = statement.limit(limit)
    return list(session.scalars(statement))


def goal_progress_for_learner(
    session: Session,
    *,
    learner_id: str,
    goal_id: str,
    mastery_threshold: float = MASTERY_THRESHOLD,
) -> dict[str, object]:
    """Return goal-relative progress: target nodes covered vs. mastered.

    ``covered`` counts target nodes with any mastery evidence; ``mastered``
    counts target nodes whose current estimate reaches ``mastery_threshold``.
    ``progress`` is the mastered/target ratio (0.0 when the goal has no targets).
    """
    goal = get_learning_goal(session, learner_id=learner_id, goal_id=goal_id)
    if goal is None:
        raise ValueError("learning goal not found for this learner")

    target_node_ids = [node.id for node in goal.target_nodes]
    target_count = len(target_node_ids)

    estimates = mastery_estimates_for_learner(session, learner_id)
    estimate_by_node = {
        str(estimate["knowledge_node_id"]): float(estimate["current_estimate"])
        for estimate in estimates
    }

    covered = sum(1 for node_id in target_node_ids if node_id in estimate_by_node)
    mastered = sum(
        1 for node_id in target_node_ids if estimate_by_node.get(node_id, 0.0) >= mastery_threshold
    )
    progress = mastered / target_count if target_count else 0.0

    return {
        "learner_id": learner_id,
        "goal_id": goal_id,
        "target_count": target_count,
        "covered_count": covered,
        "mastered_count": mastered,
        "mastery_threshold": mastery_threshold,
        "progress": round(progress, 4),
    }


def _load_goal_target_nodes(
    session: Session,
    *,
    target_node_ids: list[str],
    ownership_scope: str,
) -> list[KnowledgeNode]:
    if not target_node_ids:
        raise ValueError("learning goal requires at least one target node")

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
    draft_nodes = [node.id for node in ordered_nodes if node.status != "published"]
    if draft_nodes:
        raise ValueError("learning goals can only target published knowledge nodes")
    return ordered_nodes


def _require_learning_goal_choices(
    *,
    knowledge_type: str,
    ownership_scope: str,
    status: str,
) -> None:
    if knowledge_type not in KNOWLEDGE_TYPES:
        raise ValueError(
            f"unknown knowledge type {knowledge_type!r}; expected one of {KNOWLEDGE_TYPES}"
        )
    _require_ownership_scope(ownership_scope)
    if status not in GOAL_STATUSES:
        raise ValueError(f"unknown goal status {status!r}; expected one of {GOAL_STATUSES}")


def _require_ownership_scope(scope: str) -> None:
    if scope not in OWNERSHIP_SCOPES:
        raise ValueError(f"unknown ownership scope {scope!r}; expected one of {OWNERSHIP_SCOPES}")


def _support_dependence_markers(records: list[EvidenceRecord]) -> list[str]:
    markers: set[str] = set()
    for record in records:
        if record.hint_used:
            markers.add("hint_used")
        if record.reference_accessed:
            markers.add("reference_accessed")
        if record.support_level != "none":
            markers.add(f"support_level:{record.support_level}")
    return sorted(markers)


def _has_transfer_evidence(records: list[EvidenceRecord]) -> bool:
    """Return whether a node has evidence from a transfer-case work product."""
    for record in records:
        validity_scope = (record.validity_scope or "").strip().lower()
        if validity_scope.startswith("transfer-case:"):
            return True
        transfer_distance = (record.transfer_distance or "").strip().lower()
        if transfer_distance in TRANSFER_EVIDENCE_DISTANCES:
            return True
    return False


def _next_evidence_needed(
    *,
    current_estimate: float,
    confidence: float,
    markers: list[str],
    has_transfer_evidence: bool = False,
) -> str:
    if current_estimate < 0.6:
        return "additional successful evidence"
    if markers and not has_transfer_evidence:
        return "independent transfer evidence"
    if confidence < 0.7:
        return "more evidence to raise confidence"
    return "maintenance evidence"
