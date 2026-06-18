"""Authenticated preview API for post-demo personal capability planning.

The routes stay mounted so completed capability work remains usable, but they
are not part of the Milestones 0-4 Minimum Demo acceptance path.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

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

router = APIRouter(prefix="/capability", tags=["capability"])
SessionDep = Annotated[Session, Depends(get_session)]


@router.post(
    "/targets",
    response_model=CapabilityTargetRead,
    status_code=status.HTTP_201_CREATED,
)
def create_capability_target_route(
    payload: CapabilityTargetCreate, session: SessionDep
) -> dict[str, object]:
    """Create a personal capability target."""
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
    learner_id: Annotated[str | None, Query(max_length=36)] = None,
    target_status: Annotated[
        CapabilityTargetStatus | None,
        Query(alias="status", description="Filter by capability target status."),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[dict[str, object]]:
    """List personal capability targets."""
    targets = list_capability_targets(
        session,
        learner_id=learner_id,
        status=target_status,
        limit=limit,
    )
    return [serialize_capability_target(target) for target in targets]


@router.get("/targets/{target_id}", response_model=CapabilityTargetRead)
def get_capability_target_route(target_id: str, session: SessionDep) -> dict[str, object]:
    """Return one capability target by id."""
    target = get_capability_target(session, target_id)
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Capability target not found."
        )
    return serialize_capability_target(target)


@router.patch("/targets/{target_id}", response_model=CapabilityTargetRead)
def update_capability_target_route(
    target_id: str,
    payload: CapabilityTargetUpdate,
    session: SessionDep,
) -> dict[str, object]:
    """Update a personal capability target."""
    target = get_capability_target(session, target_id)
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Capability target not found."
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
def archive_capability_target_route(target_id: str, session: SessionDep) -> dict[str, object]:
    """Archive a capability target without deleting it."""
    target = get_capability_target(session, target_id)
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Capability target not found."
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
) -> dict[str, object]:
    """Recompute and persist a capability estimate for one personal target."""
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
    learner_id: Annotated[str | None, Query(max_length=36)] = None,
    target_id: Annotated[str | None, Query(max_length=36)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[dict[str, object]]:
    """List persisted capability estimates."""
    estimates = list_capability_estimates(
        session,
        learner_id=learner_id,
        target_id=target_id,
        limit=limit,
    )
    return [serialize_capability_estimate(estimate) for estimate in estimates]


@router.get("/estimates/{estimate_id}", response_model=CapabilityEstimateRead)
def get_capability_estimate_route(estimate_id: str, session: SessionDep) -> dict[str, object]:
    """Return one persisted capability estimate by id."""
    estimate = get_capability_estimate(session, estimate_id)
    if estimate is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Capability estimate not found.",
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
) -> dict[str, object]:
    """Generate and persist a gap analysis from one capability estimate."""
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
    learner_id: Annotated[str | None, Query(max_length=36)] = None,
    target_id: Annotated[str | None, Query(max_length=36)] = None,
    estimate_id: Annotated[str | None, Query(max_length=36)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[dict[str, object]]:
    """List persisted gap analyses."""
    analyses = list_gap_analyses(
        session,
        learner_id=learner_id,
        target_id=target_id,
        estimate_id=estimate_id,
        limit=limit,
    )
    return [serialize_gap_analysis(analysis) for analysis in analyses]


@router.get("/gap-analyses/{analysis_id}", response_model=GapAnalysisRead)
def get_gap_analysis_route(analysis_id: str, session: SessionDep) -> dict[str, object]:
    """Return one persisted gap analysis by id."""
    analysis = get_gap_analysis(session, analysis_id)
    if analysis is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Gap analysis not found.",
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
) -> dict[str, object]:
    """Generate and persist a maintenance plan from one gap analysis."""
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
    learner_id: Annotated[str | None, Query(max_length=36)] = None,
    target_id: Annotated[str | None, Query(max_length=36)] = None,
    gap_analysis_id: Annotated[str | None, Query(max_length=36)] = None,
    plan_status: Annotated[
        MaintenancePlanStatus | None,
        Query(alias="status", description="Filter by maintenance plan status."),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[dict[str, object]]:
    """List persisted maintenance plans."""
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
def get_maintenance_plan_route(plan_id: str, session: SessionDep) -> dict[str, object]:
    """Return one persisted maintenance plan by id."""
    plan = get_maintenance_plan(session, plan_id)
    if plan is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Maintenance plan not found.",
        )
    return serialize_maintenance_plan(plan)
