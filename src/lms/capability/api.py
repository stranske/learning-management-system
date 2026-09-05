"""Authenticated preview API for post-demo personal capability planning.

The routes stay mounted so completed capability work remains usable, but they
are not part of the Milestones 0-4 Minimum Demo acceptance path.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from lms.auth.login import SettingsDep
from lms.auth.models import User
from lms.capability.models import CapabilityEstimate, CapabilityTarget, GapAnalysis, MaintenancePlan
from lms.capability.repository import (
    archive_capability_target,
    create_capability_target,
    create_gap_analysis,
    create_maintenance_plan,
    get_capability_estimate,
    get_capability_target,
    get_gap_analysis,
    get_maintenance_plan,
    list_capability_estimates,
    list_capability_targets,
    list_gap_analyses,
    list_maintenance_plans,
    recompute_capability_estimate,
    serialize_capability_estimate,
    serialize_capability_target,
    serialize_gap_analysis,
    serialize_maintenance_plan,
    update_capability_target,
)
from lms.capability.schemas import (
    CapabilityEstimateRead,
    CapabilityEstimateRecompute,
    CapabilityTargetCreate,
    CapabilityTargetRead,
    CapabilityTargetStatus,
    CapabilityTargetUpdate,
    GapAnalysisCreate,
    GapAnalysisRead,
    MaintenancePlanCreate,
    MaintenancePlanRead,
    MaintenancePlanStatus,
)
from lms.db.session import get_session
from lms.learners.identity import CurrentUserDep, require_learner_ownership, resolve_learner_id
from lms.settings import Settings

router = APIRouter(prefix="/capability", tags=["capability"])
SessionDep = Annotated[Session, Depends(get_session)]


def _owned_resource[T: CapabilityTarget | CapabilityEstimate | GapAnalysis | MaintenancePlan](
    session: Session,
    resource: T | None,
    user: User,
    settings: Settings,
    *,
    label: str = "Learner resource",
) -> T:
    """Return an owned record, masking missing and foreign deployed resources."""
    if resource is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "Learner resource not found." if settings.auth_required else f"{label} not found."
            ),
        )
    require_learner_ownership(session, user=user, settings=settings, learner_id=resource.learner_id)
    return resource


def _require_resource_ownership(
    session: Session,
    resource: CapabilityTarget | CapabilityEstimate | GapAnalysis | None,
    user: User,
    settings: Settings,
) -> str:
    """Authorize a referenced record before deriving or filtering private data."""
    return _owned_resource(session, resource, user, settings).learner_id


def _scoped_learner_id(
    session: Session,
    user: User,
    settings: Settings,
    learner_id: str | None,
    *,
    target_id: str | None = None,
    estimate_id: str | None = None,
    gap_analysis_id: str | None = None,
) -> str | None:
    """Scope collections, preserving owned parent filters and local preview mode."""
    if not settings.auth_required:
        return learner_id
    referenced_learner_id = None
    for resource_id, getter in (
        (target_id, get_capability_target),
        (estimate_id, get_capability_estimate),
        (gap_analysis_id, get_gap_analysis),
    ):
        if resource_id is not None:
            referenced_learner_id = _require_resource_ownership(
                session, getter(session, resource_id), user, settings
            )
    return resolve_learner_id(
        session, user=user, settings=settings, requested=learner_id or referenced_learner_id
    )


@router.post(
    "/targets",
    response_model=CapabilityTargetRead,
    status_code=status.HTTP_201_CREATED,
)
def create_capability_target_route(
    payload: CapabilityTargetCreate,
    session: SessionDep,
    current_user: CurrentUserDep,
    settings: SettingsDep,
) -> dict[str, object]:
    """Create a personal capability target."""
    require_learner_ownership(
        session, user=current_user, settings=settings, learner_id=payload.learner_id
    )
    try:
        target = create_capability_target(
            session,
            learner_id=payload.learner_id,
            title=payload.title,
            description=payload.description,
            ownership_scope=payload.ownership_scope,
            learning_goal_id=payload.learning_goal_id,
            target_node_ids=payload.target_node_ids,
            target_competency_ids=payload.target_competency_ids,
            required_evidence_types=payload.required_evidence_types,
            confidence_threshold=payload.confidence_threshold,
            status=payload.status,
        )
        session.commit()
        session.refresh(target)
    except ValueError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return serialize_capability_target(target)


@router.get("/targets", response_model=list[CapabilityTargetRead])
def list_capability_targets_route(
    session: SessionDep,
    current_user: CurrentUserDep,
    settings: SettingsDep,
    learner_id: Annotated[str | None, Query(min_length=1, max_length=36)] = None,
    target_status: Annotated[
        CapabilityTargetStatus | None,
        Query(alias="status", description="Filter by capability target status."),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[dict[str, object]]:
    """List personal capability targets."""
    learner_id = _scoped_learner_id(session, current_user, settings, learner_id)
    targets = list_capability_targets(
        session,
        learner_id=learner_id,
        status=target_status,
        limit=limit,
    )
    return [serialize_capability_target(target) for target in targets]


@router.get("/targets/{target_id}", response_model=CapabilityTargetRead)
def get_capability_target_route(
    target_id: str,
    session: SessionDep,
    current_user: CurrentUserDep,
    settings: SettingsDep,
) -> dict[str, object]:
    """Return one capability target by id."""
    target = _owned_resource(
        session,
        get_capability_target(session, target_id),
        current_user,
        settings,
        label="Capability target",
    )
    return serialize_capability_target(target)


@router.patch("/targets/{target_id}", response_model=CapabilityTargetRead)
def update_capability_target_route(
    target_id: str,
    payload: CapabilityTargetUpdate,
    session: SessionDep,
    current_user: CurrentUserDep,
    settings: SettingsDep,
) -> dict[str, object]:
    """Update a personal capability target."""
    target = _owned_resource(
        session,
        get_capability_target(session, target_id),
        current_user,
        settings,
        label="Capability target",
    )
    try:
        updated = update_capability_target(
            session,
            target,
            **payload.model_dump(exclude_unset=True),
        )
        session.commit()
        session.refresh(updated)
    except ValueError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return serialize_capability_target(updated)


@router.post("/targets/{target_id}/archive", response_model=CapabilityTargetRead)
def archive_capability_target_route(
    target_id: str,
    session: SessionDep,
    current_user: CurrentUserDep,
    settings: SettingsDep,
) -> dict[str, object]:
    """Archive a capability target without deleting it."""
    target = _owned_resource(
        session,
        get_capability_target(session, target_id),
        current_user,
        settings,
        label="Capability target",
    )
    archived = archive_capability_target(session, target)
    session.commit()
    session.refresh(archived)
    return serialize_capability_target(archived)


@router.post(
    "/estimates", response_model=CapabilityEstimateRead, status_code=status.HTTP_201_CREATED
)
def recompute_capability_estimate_route(
    payload: CapabilityEstimateRecompute,
    session: SessionDep,
    current_user: CurrentUserDep,
    settings: SettingsDep,
) -> dict[str, object]:
    """Recompute and persist a capability estimate for one personal target."""
    if settings.auth_required:
        _require_resource_ownership(
            session, get_capability_target(session, payload.target_id), current_user, settings
        )
    try:
        estimate = recompute_capability_estimate(session, target_id=payload.target_id)
        session.commit()
        session.refresh(estimate)
    except ValueError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    return serialize_capability_estimate(estimate)


@router.get("/estimates", response_model=list[CapabilityEstimateRead])
def list_capability_estimates_route(
    session: SessionDep,
    current_user: CurrentUserDep,
    settings: SettingsDep,
    learner_id: Annotated[str | None, Query(min_length=1, max_length=36)] = None,
    target_id: Annotated[str | None, Query(min_length=1, max_length=36)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[dict[str, object]]:
    """List persisted capability estimates."""
    learner_id = _scoped_learner_id(
        session, current_user, settings, learner_id, target_id=target_id
    )
    estimates = list_capability_estimates(
        session,
        learner_id=learner_id,
        target_id=target_id,
        limit=limit,
    )
    return [serialize_capability_estimate(estimate) for estimate in estimates]


@router.get("/estimates/{estimate_id}", response_model=CapabilityEstimateRead)
def get_capability_estimate_route(
    estimate_id: str,
    session: SessionDep,
    current_user: CurrentUserDep,
    settings: SettingsDep,
) -> dict[str, object]:
    """Return one persisted capability estimate by id."""
    estimate = _owned_resource(
        session,
        get_capability_estimate(session, estimate_id),
        current_user,
        settings,
        label="Capability estimate",
    )
    return serialize_capability_estimate(estimate)


@router.post(
    "/gap-analyses",
    response_model=GapAnalysisRead,
    status_code=status.HTTP_201_CREATED,
)
def create_gap_analysis_route(
    payload: GapAnalysisCreate,
    session: SessionDep,
    current_user: CurrentUserDep,
    settings: SettingsDep,
) -> dict[str, object]:
    """Generate and persist a gap analysis from one capability estimate."""
    if settings.auth_required:
        _require_resource_ownership(
            session, get_capability_estimate(session, payload.estimate_id), current_user, settings
        )
    try:
        analysis = create_gap_analysis(session, estimate_id=payload.estimate_id)
        session.commit()
        session.refresh(analysis)
    except ValueError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    return serialize_gap_analysis(analysis)


@router.get("/gap-analyses", response_model=list[GapAnalysisRead])
def list_gap_analyses_route(
    session: SessionDep,
    current_user: CurrentUserDep,
    settings: SettingsDep,
    learner_id: Annotated[str | None, Query(min_length=1, max_length=36)] = None,
    target_id: Annotated[str | None, Query(min_length=1, max_length=36)] = None,
    estimate_id: Annotated[str | None, Query(min_length=1, max_length=36)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[dict[str, object]]:
    """List persisted gap analyses."""
    learner_id = _scoped_learner_id(
        session, current_user, settings, learner_id, target_id=target_id, estimate_id=estimate_id
    )
    analyses = list_gap_analyses(
        session,
        learner_id=learner_id,
        target_id=target_id,
        estimate_id=estimate_id,
        limit=limit,
    )
    return [serialize_gap_analysis(analysis) for analysis in analyses]


@router.get("/gap-analyses/{analysis_id}", response_model=GapAnalysisRead)
def get_gap_analysis_route(
    analysis_id: str,
    session: SessionDep,
    current_user: CurrentUserDep,
    settings: SettingsDep,
) -> dict[str, object]:
    """Return one persisted gap analysis by id."""
    analysis = _owned_resource(
        session,
        get_gap_analysis(session, analysis_id),
        current_user,
        settings,
        label="Gap analysis",
    )
    return serialize_gap_analysis(analysis)


@router.post(
    "/maintenance-plans",
    response_model=MaintenancePlanRead,
    status_code=status.HTTP_201_CREATED,
)
def create_maintenance_plan_route(
    payload: MaintenancePlanCreate,
    session: SessionDep,
    current_user: CurrentUserDep,
    settings: SettingsDep,
) -> dict[str, object]:
    """Generate and persist a maintenance plan from one gap analysis."""
    if settings.auth_required:
        _require_resource_ownership(
            session, get_gap_analysis(session, payload.gap_analysis_id), current_user, settings
        )
    try:
        plan = create_maintenance_plan(session, gap_analysis_id=payload.gap_analysis_id)
        session.commit()
        session.refresh(plan)
    except ValueError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    return serialize_maintenance_plan(plan)


@router.get("/maintenance-plans", response_model=list[MaintenancePlanRead])
def list_maintenance_plans_route(
    session: SessionDep,
    current_user: CurrentUserDep,
    settings: SettingsDep,
    learner_id: Annotated[str | None, Query(min_length=1, max_length=36)] = None,
    target_id: Annotated[str | None, Query(min_length=1, max_length=36)] = None,
    gap_analysis_id: Annotated[str | None, Query(min_length=1, max_length=36)] = None,
    plan_status: Annotated[
        MaintenancePlanStatus | None,
        Query(alias="status", description="Filter by maintenance plan status."),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[dict[str, object]]:
    """List persisted maintenance plans."""
    learner_id = _scoped_learner_id(
        session,
        current_user,
        settings,
        learner_id,
        target_id=target_id,
        gap_analysis_id=gap_analysis_id,
    )
    plans = list_maintenance_plans(
        session,
        learner_id=learner_id,
        target_id=target_id,
        gap_analysis_id=gap_analysis_id,
        status=plan_status,
        limit=limit,
    )
    return [serialize_maintenance_plan(plan) for plan in plans]


@router.get("/maintenance-plans/{plan_id}", response_model=MaintenancePlanRead)
def get_maintenance_plan_route(
    plan_id: str,
    session: SessionDep,
    current_user: CurrentUserDep,
    settings: SettingsDep,
) -> dict[str, object]:
    """Return one persisted maintenance plan by id."""
    plan = _owned_resource(
        session,
        get_maintenance_plan(session, plan_id),
        current_user,
        settings,
        label="Maintenance plan",
    )
    return serialize_maintenance_plan(plan)
