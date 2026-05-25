"""HTTP CRUD routes for source references."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from lms.db.session import get_session
from lms.sources.repository import (
    create_source_reference,
    delete_source_reference,
    get_source_reference,
    list_source_references,
    update_source_reference,
)
from lms.sources.schemas import SourceReferenceCreate, SourceReferenceRead, SourceReferenceUpdate

router = APIRouter(prefix="/source-references", tags=["source-references"])
SessionDep = Annotated[Session, Depends(get_session)]


@router.post("", response_model=SourceReferenceRead, status_code=status.HTTP_201_CREATED)
def create_source_reference_route(
    payload: SourceReferenceCreate,
    session: SessionDep,
) -> SourceReferenceRead:
    """Create a source reference and record an audit event."""
    if (
        payload.source_type == "markdown-file"
        and payload.content is None
        and payload.content_hash is None
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "content or content_hash is required for markdown-file source references "
                "created via the HTTP API"
            ),
        )
    try:
        reference = create_source_reference(
            session,
            source_type=payload.source_type,
            stable_locator=payload.stable_locator,
            passage_range=payload.passage_range,
            content=payload.content,
            content_hash=payload.content_hash,
            hash_algorithm=payload.hash_algorithm,
            source_visibility=payload.source_visibility,
            multi_source_role=payload.multi_source_role,
            actor_id=payload.actor_id,
            source_subsystem="api",
        )
        session.commit()
        session.refresh(reference)
    except ValueError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return SourceReferenceRead.model_validate(reference)


@router.get("", response_model=list[SourceReferenceRead])
def list_source_references_route(
    session: SessionDep,
    source_type: Annotated[str | None, Query(description="Filter by source type.")] = None,
    drift_status: Annotated[str | None, Query(description="Filter by drift status.")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[SourceReferenceRead]:
    """Return source references filtered by type and/or drift status."""
    references = list_source_references(
        session,
        source_type=source_type,
        drift_status=drift_status,
        limit=limit,
    )
    return [SourceReferenceRead.model_validate(reference) for reference in references]


@router.get("/{reference_id}", response_model=SourceReferenceRead)
def get_source_reference_route(reference_id: str, session: SessionDep) -> SourceReferenceRead:
    """Return one source reference by id."""
    reference = get_source_reference(session, reference_id)
    if reference is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Source reference not found."
        )
    return SourceReferenceRead.model_validate(reference)


@router.patch("/{reference_id}", response_model=SourceReferenceRead)
def update_source_reference_route(
    reference_id: str,
    payload: SourceReferenceUpdate,
    session: SessionDep,
) -> SourceReferenceRead:
    """Update a source reference and record an audit event."""
    reference = get_source_reference(session, reference_id)
    if reference is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Source reference not found."
        )
    changes = payload.model_dump(exclude={"actor_id", "content"}, exclude_none=True)
    try:
        updated = update_source_reference(
            session,
            reference,
            actor_id=payload.actor_id,
            content=payload.content,
            **changes,
        )
        session.commit()
        session.refresh(updated)
    except ValueError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return SourceReferenceRead.model_validate(updated)


@router.delete("/{reference_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_source_reference_route(
    reference_id: str,
    session: SessionDep,
    actor_id: Annotated[str, Query(min_length=1, max_length=255)] = "system:api",
) -> Response:
    """Delete a source reference and record an audit event."""
    reference = get_source_reference(session, reference_id)
    if reference is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Source reference not found."
        )
    delete_source_reference(session, reference, actor_id=actor_id)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
