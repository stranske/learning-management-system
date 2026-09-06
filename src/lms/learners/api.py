"""Learner API routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from lms.auth.login import SettingsDep, require_authenticated_user
from lms.auth.models import User
from lms.auth.repository import get_user
from lms.db.session import get_session
from lms.graphs.schemas import OwnershipScope
from lms.learners.identity import require_learner_ownership
from lms.learners.models import Learner, LearnerReflection, LearningGoal
from lms.learners.repository import (
    create_learner_for_user,
    create_learning_goal,
    create_reflection,
    get_learner,
    get_learning_goal,
    goal_progress_for_learner,
    knowledge_profile_for_learner,
    list_learning_goals_for_learner,
    list_reflections_for_learner,
    update_learning_goal,
)
from lms.learners.schemas import (
    GoalProgressRead,
    GoalStatus,
    KnowledgeProfileRead,
    LearnerCreate,
    LearnerRead,
    LearningGoalCreate,
    LearningGoalRead,
    LearningGoalUpdate,
    ReflectionCreate,
    ReflectionRead,
)

router = APIRouter(prefix="/learners", tags=["learners"])
SessionDep = Annotated[Session, Depends(get_session)]
CurrentUserDep = Annotated[User, Depends(require_authenticated_user)]


@router.post("", response_model=LearnerRead, status_code=status.HTTP_201_CREATED)
def create_learner(
    payload: LearnerCreate,
    session: SessionDep,
    current_user: CurrentUserDep,
    settings: SettingsDep,
) -> Learner:
    """Create a learner profile for an explicit user id."""
    if settings.auth_required and current_user.id != payload.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot create a learner for another user.",
        )
    if get_user(session, payload.user_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    learner = create_learner_for_user(
        session,
        user_id=payload.user_id,
        display_name=payload.display_name,
        timezone=payload.timezone,
        locale=payload.locale,
    )
    session.commit()
    session.refresh(learner)
    return learner


@router.post(
    "/{learner_id}/learning-goals",
    response_model=LearningGoalRead,
    status_code=status.HTTP_201_CREATED,
)
def create_learning_goal_route(
    learner_id: str,
    payload: LearningGoalCreate,
    session: SessionDep,
    current_user: CurrentUserDep,
    settings: SettingsDep,
) -> LearningGoal:
    """Create a learner goal linked to published knowledge nodes."""
    require_learner_ownership(session, user=current_user, settings=settings, learner_id=learner_id)
    if get_learner(session, learner_id=learner_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Learner not found.")
    try:
        goal = create_learning_goal(
            session,
            learner_id=learner_id,
            title=payload.title,
            knowledge_type=payload.knowledge_type,
            target_node_ids=payload.target_node_ids,
            ownership_scope=payload.ownership_scope,
            status=payload.status,
        )
        session.commit()
        session.refresh(goal)
    except ValueError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    return goal


@router.get("/{learner_id}/learning-goals", response_model=list[LearningGoalRead])
def list_learning_goals_route(
    learner_id: str,
    session: SessionDep,
    current_user: CurrentUserDep,
    settings: SettingsDep,
    ownership_scope: Annotated[
        OwnershipScope | None,
        Query(description="Optional ownership-scope filter."),
    ] = None,
    goal_status: Annotated[
        GoalStatus | None,
        Query(alias="status", description="Optional goal status filter."),
    ] = None,
) -> list[LearningGoal]:
    """Return goals for exactly one learner."""
    require_learner_ownership(session, user=current_user, settings=settings, learner_id=learner_id)
    if get_learner(session, learner_id=learner_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Learner not found.")
    try:
        return list_learning_goals_for_learner(
            session,
            learner_id=learner_id,
            ownership_scope=ownership_scope,
            status=goal_status,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.get("/{learner_id}/knowledge-profile", response_model=KnowledgeProfileRead)
def read_knowledge_profile_route(
    learner_id: str,
    session: SessionDep,
    current_user: CurrentUserDep,
    settings: SettingsDep,
    ownership_scope: Annotated[
        OwnershipScope,
        Query(description="Graph ownership scope to summarize."),
    ] = "personal",
) -> dict[str, object]:
    """Return the learner's computed knowledge profile for one graph scope."""
    require_learner_ownership(session, user=current_user, settings=settings, learner_id=learner_id)
    if get_learner(session, learner_id=learner_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Learner not found.")
    try:
        return knowledge_profile_for_learner(
            session,
            learner_id=learner_id,
            ownership_scope=ownership_scope,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.patch(
    "/{learner_id}/learning-goals/{goal_id}",
    response_model=LearningGoalRead,
)
def update_learning_goal_route(
    learner_id: str,
    goal_id: str,
    payload: LearningGoalUpdate,
    session: SessionDep,
    current_user: CurrentUserDep,
    settings: SettingsDep,
) -> LearningGoal:
    """Update a learner goal and optionally retarget published nodes."""
    require_learner_ownership(session, user=current_user, settings=settings, learner_id=learner_id)
    goal = get_learning_goal(session, learner_id=learner_id, goal_id=goal_id)
    if goal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Learning goal not found."
        )
    try:
        updated = update_learning_goal(
            session,
            goal,
            **payload.model_dump(exclude_none=True),
        )
        session.commit()
        session.refresh(updated)
    except ValueError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    return updated


@router.post(
    "/{learner_id}/reflections",
    response_model=ReflectionRead,
    status_code=status.HTTP_201_CREATED,
)
def create_reflection_route(
    learner_id: str,
    payload: ReflectionCreate,
    session: SessionDep,
    current_user: CurrentUserDep,
    settings: SettingsDep,
) -> LearnerReflection:
    """Record a learner's metacognitive reflection after a review."""
    require_learner_ownership(session, user=current_user, settings=settings, learner_id=learner_id)
    if get_learner(session, learner_id=learner_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Learner not found.")
    try:
        reflection = create_reflection(
            session,
            learner_id=learner_id,
            prompt=payload.prompt,
            response=payload.response,
            knowledge_node_id=payload.knowledge_node_id,
        )
        session.commit()
        session.refresh(reflection)
    except ValueError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    return reflection


@router.get("/{learner_id}/reflections", response_model=list[ReflectionRead])
def list_reflections_route(
    learner_id: str,
    session: SessionDep,
    current_user: CurrentUserDep,
    settings: SettingsDep,
) -> list[LearnerReflection]:
    """Surface a learner's recorded reflections, newest first."""
    require_learner_ownership(session, user=current_user, settings=settings, learner_id=learner_id)
    if get_learner(session, learner_id=learner_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Learner not found.")
    return list_reflections_for_learner(session, learner_id=learner_id)


@router.get(
    "/{learner_id}/learning-goals/{goal_id}/progress",
    response_model=GoalProgressRead,
)
def read_goal_progress_route(
    learner_id: str,
    goal_id: str,
    session: SessionDep,
    current_user: CurrentUserDep,
    settings: SettingsDep,
) -> dict[str, object]:
    """Return goal-relative progress (target nodes covered vs. mastered)."""
    require_learner_ownership(session, user=current_user, settings=settings, learner_id=learner_id)
    if get_learner(session, learner_id=learner_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Learner not found.")
    try:
        return goal_progress_for_learner(
            session,
            learner_id=learner_id,
            goal_id=goal_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
