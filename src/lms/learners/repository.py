"""Repository helpers for learner profiles."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from lms.graphs.models import KNOWLEDGE_TYPES, KnowledgeNode
from lms.graphs.repository import _require_scope
from lms.learners.models import GOAL_STATUSES, Learner, LearningGoal


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
        _require_scope(ownership_scope)
        statement = statement.where(LearningGoal.ownership_scope == ownership_scope)
    if status is not None:
        if status not in GOAL_STATUSES:
            raise ValueError(f"unknown goal status {status!r}; expected one of {GOAL_STATUSES}")
        statement = statement.where(LearningGoal.status == status)
    statement = statement.order_by(LearningGoal.created_at.desc(), LearningGoal.id)
    return list(session.scalars(statement))


def _load_goal_target_nodes(
    session: Session,
    *,
    target_node_ids: list[str],
    ownership_scope: str,
) -> list[KnowledgeNode]:
    if not target_node_ids:
        raise ValueError("learning goal requires at least one target node")

    nodes = list(
        session.scalars(select(KnowledgeNode).where(KnowledgeNode.id.in_(target_node_ids)))
    )
    found_by_id = {node.id: node for node in nodes}
    missing = [node_id for node_id in target_node_ids if node_id not in found_by_id]
    if missing:
        raise ValueError(f"target knowledge nodes not found: {', '.join(missing)}")

    ordered_nodes = [found_by_id[node_id] for node_id in target_node_ids]
    wrong_scope = [node.id for node in ordered_nodes if node.ownership_scope != ownership_scope]
    if wrong_scope:
        raise ValueError("target knowledge nodes must match the goal ownership scope")
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
    _require_scope(ownership_scope)
    if status not in GOAL_STATUSES:
        raise ValueError(f"unknown goal status {status!r}; expected one of {GOAL_STATUSES}")
