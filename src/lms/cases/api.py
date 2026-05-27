"""HTTP routes for transfer case shells."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from lms.cases.repository import (
    add_case_step,
    add_decision_point,
    add_evidence_packet,
    create_case,
    create_work_product,
    get_case,
    get_work_product,
    list_cases,
    list_work_products,
    serialize_case,
    serialize_case_step,
    serialize_decision_point,
    serialize_evidence_packet,
    serialize_work_product,
)
from lms.cases.schemas import (
    CaseCreate,
    CaseRead,
    CaseStatus,
    CaseStepCreate,
    CaseStepRead,
    DecisionPointCreate,
    DecisionPointRead,
    EvidencePacketCreate,
    EvidencePacketRead,
    OwnershipScope,
    WorkProductCreate,
    WorkProductRead,
    WorkProductStatus,
)
from lms.db.session import get_session

router = APIRouter(tags=["cases"])
SessionDep = Annotated[Session, Depends(get_session)]


@router.post("/cases", response_model=CaseRead, status_code=status.HTTP_201_CREATED)
def create_case_route(payload: CaseCreate, session: SessionDep) -> dict[str, object]:
    """Create a transfer case shell."""
    data = payload.model_dump()
    try:
        case = create_case(session, **data)
        session.commit()
        case = get_case(session, case.id) or case
    except ValueError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return serialize_case(case)


@router.get("/cases", response_model=list[CaseRead])
def list_cases_route(
    session: SessionDep,
    ownership_scope: Annotated[OwnershipScope | None, Query()] = None,
    rubric_id: Annotated[str | None, Query(min_length=1, max_length=36)] = None,
    knowledge_node_id: Annotated[str | None, Query(min_length=1, max_length=36)] = None,
    case_status: Annotated[CaseStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[dict[str, object]]:
    """List transfer case shells."""
    cases = list_cases(
        session,
        ownership_scope=ownership_scope,
        rubric_id=rubric_id,
        knowledge_node_id=knowledge_node_id,
        status=case_status,
        limit=limit,
    )
    return [serialize_case(case) for case in cases]


@router.get("/cases/{case_id}", response_model=CaseRead)
def get_case_route(case_id: str, session: SessionDep) -> dict[str, object]:
    """Return one transfer case shell."""
    case = get_case(session, case_id)
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found.")
    return serialize_case(case)


@router.post(
    "/cases/{case_id}/steps", response_model=CaseStepRead, status_code=status.HTTP_201_CREATED
)
def add_case_step_route(
    case_id: str, payload: CaseStepCreate, session: SessionDep
) -> dict[str, object]:
    """Add an ordered step to a transfer case."""
    try:
        step = add_case_step(session, case_id=case_id, **payload.model_dump())
        session.commit()
        session.refresh(step)
    except ValueError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return serialize_case_step(step)


@router.post(
    "/cases/{case_id}/evidence-packets",
    response_model=EvidencePacketRead,
    status_code=status.HTTP_201_CREATED,
)
def add_evidence_packet_route(
    case_id: str, payload: EvidencePacketCreate, session: SessionDep
) -> dict[str, object]:
    """Add an evidence packet to a transfer case."""
    try:
        packet = add_evidence_packet(session, case_id=case_id, **payload.model_dump())
        session.commit()
        session.refresh(packet)
    except ValueError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return serialize_evidence_packet(packet)


@router.post(
    "/decision-points", response_model=DecisionPointRead, status_code=status.HTTP_201_CREATED
)
def add_decision_point_route(
    payload: DecisionPointCreate, session: SessionDep
) -> dict[str, object]:
    """Add a stored decision point to a case step."""
    try:
        decision = add_decision_point(session, **payload.model_dump())
        session.commit()
        session.refresh(decision)
    except ValueError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return serialize_decision_point(decision)


@router.post(
    "/cases/{case_id}/work-products",
    response_model=WorkProductRead,
    status_code=status.HTTP_201_CREATED,
)
def submit_work_product_route(
    case_id: str, payload: WorkProductCreate, session: SessionDep
) -> dict[str, object]:
    """Submit a learner work product for a transfer case."""
    if get_case(session, case_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found.")
    try:
        work_product = create_work_product(
            session,
            case_id=case_id,
            status="submitted",
            **payload.model_dump(),
        )
        session.commit()
        session.refresh(work_product)
    except ValueError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return serialize_work_product(work_product)


@router.get("/cases/{case_id}/work-products", response_model=list[WorkProductRead])
def list_work_products_route(
    case_id: str,
    session: SessionDep,
    learner_id: Annotated[str | None, Query(min_length=1, max_length=36)] = None,
    case_step_id: Annotated[str | None, Query(min_length=1, max_length=36)] = None,
    work_product_status: Annotated[WorkProductStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[dict[str, object]]:
    """List work products submitted for a transfer case."""
    if get_case(session, case_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found.")
    work_products = list_work_products(
        session,
        case_id=case_id,
        learner_id=learner_id,
        case_step_id=case_step_id,
        status=work_product_status,
        limit=limit,
    )
    return [serialize_work_product(work_product) for work_product in work_products]


@router.get("/work-products/{work_product_id}", response_model=WorkProductRead)
def get_work_product_route(work_product_id: str, session: SessionDep) -> dict[str, object]:
    """Return one work product."""
    work_product = get_work_product(session, work_product_id)
    if work_product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Work product not found.")
    return serialize_work_product(work_product)
