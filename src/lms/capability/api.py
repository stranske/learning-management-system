"""HTTP routes for personal capability targets."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from lms.capability.repository import (
    archive_capability_target,
    create_capability_target,
    get_capability_estimate,
    get_capability_target,
    list_capability_estimates,
    list_capability_targets,
    recompute_capability_estimate,
    serialize_capability_estimate,
    serialize_capability_target,
    update_capability_target,
)
from lms.capability.schemas import (
    CapabilityEstimateRead,
    CapabilityEstimateRecompute,
    CapabilityTargetCreate,
    CapabilityTargetRead,
    CapabilityTargetStatus,
    CapabilityTargetUpdate,
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
