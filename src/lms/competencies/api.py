"""HTTP routes for competencies and competency evidence."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from lms.competencies.repository import (
    create_competency,
    create_competency_evidence,
    evidence_for_competency_learner,
    get_competency,
    list_competencies,
    list_competency_evidence,
)
from lms.competencies.schemas import (
    CompetencyCreate,
    CompetencyEvidenceCreate,
    CompetencyEvidenceRead,
    CompetencyRead,
    CompetencyStatus,
)
from lms.db.session import get_session
from lms.graphs.schemas import KnowledgeType, OwnershipScope

router = APIRouter(tags=["competencies"])
SessionDep = Annotated[Session, Depends(get_session)]


@router.post("/competencies", response_model=CompetencyRead, status_code=status.HTTP_201_CREATED)
def create_competency_route(payload: CompetencyCreate, session: SessionDep) -> CompetencyRead:
    """Create an observable competency definition."""
    try:
        competency = create_competency(
            session,
            title=payload.title,
            description=payload.description,
            ownership_scope=payload.ownership_scope,
            target_knowledge_type=payload.target_knowledge_type,
            validity_scope=payload.validity_scope,
            status=payload.status,
        )
        session.commit()
        session.refresh(competency)
    except ValueError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return CompetencyRead.model_validate(competency)


@router.get("/competencies", response_model=list[CompetencyRead])
def list_competencies_route(
    session: SessionDep,
    ownership_scope: Annotated[OwnershipScope | None, Query()] = None,
    competency_status: Annotated[
        CompetencyStatus | None,
        Query(alias="status", description="Filter by competency status."),
    ] = None,
    target_knowledge_type: Annotated[KnowledgeType | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[CompetencyRead]:
    """List competency definitions."""
    competencies = list_competencies(
        session,
        ownership_scope=ownership_scope,
        status=competency_status,
        target_knowledge_type=target_knowledge_type,
        limit=limit,
    )
    return [CompetencyRead.model_validate(competency) for competency in competencies]


@router.get("/competencies/{competency_id}", response_model=CompetencyRead)
def get_competency_route(competency_id: str, session: SessionDep) -> CompetencyRead:
    """Return one competency by id."""
    competency = get_competency(session, competency_id)
    if competency is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Competency not found.")
    return CompetencyRead.model_validate(competency)


@router.post(
    "/competency-evidence",
    response_model=CompetencyEvidenceRead,
    status_code=status.HTTP_201_CREATED,
)
def create_competency_evidence_route(
    payload: CompetencyEvidenceCreate, session: SessionDep
) -> CompetencyEvidenceRead:
    """Create a link between a competency, knowledge node, and evidence record."""
    try:
        link = create_competency_evidence(
            session,
            competency_id=payload.competency_id,
            knowledge_node_id=payload.knowledge_node_id,
            evidence_record_id=payload.evidence_record_id,
            contribution_weight=payload.contribution_weight,
            evidence_role=payload.evidence_role,
            actor_id=payload.actor_id,
        )
        session.commit()
        session.refresh(link)
    except ValueError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return CompetencyEvidenceRead.model_validate(link)


@router.get("/competency-evidence", response_model=list[CompetencyEvidenceRead])
def list_competency_evidence_route(
    session: SessionDep,
    competency_id: Annotated[str | None, Query(max_length=36)] = None,
    learner_id: Annotated[str | None, Query(max_length=36)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[CompetencyEvidenceRead]:
    """List competency evidence links."""
    links = list_competency_evidence(
        session,
        competency_id=competency_id,
        learner_id=learner_id,
        limit=limit,
    )
    return [CompetencyEvidenceRead.model_validate(link) for link in links]


@router.get(
    "/competencies/{competency_id}/evidence",
    response_model=list[CompetencyEvidenceRead],
)
def learner_evidence_for_competency_route(
    competency_id: str,
    session: SessionDep,
    learner_id: Annotated[str, Query(min_length=1, max_length=36)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[CompetencyEvidenceRead]:
    """Return evidence contributing to one learner's competency estimate."""
    links = evidence_for_competency_learner(
        session,
        competency_id=competency_id,
        learner_id=learner_id,
        limit=limit,
    )
    return [CompetencyEvidenceRead.model_validate(link) for link in links]

