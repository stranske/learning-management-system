"""HTTP CRUD routes for scoped knowledge graph records."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from lms.db.session import get_session
from lms.graphs.repository import (
    create_graph_reference,
    create_knowledge_edge,
    create_knowledge_node,
    get_knowledge_edge,
    get_knowledge_node,
    list_knowledge_edges,
    list_knowledge_nodes,
)
from lms.graphs.schemas import (
    GraphReferenceCreate,
    GraphReferenceRead,
    KnowledgeEdgeCreate,
    KnowledgeEdgeRead,
    KnowledgeNodeCreate,
    KnowledgeNodeRead,
)

router = APIRouter(prefix="/knowledge", tags=["knowledge"])
SessionDep = Annotated[Session, Depends(get_session)]


@router.post("/nodes", response_model=KnowledgeNodeRead, status_code=status.HTTP_201_CREATED)
def create_knowledge_node_route(
    payload: KnowledgeNodeCreate,
    session: SessionDep,
) -> KnowledgeNodeRead:
    """Create a knowledge node and record an audit event."""
    try:
        node = create_knowledge_node(
            session,
            title=payload.title,
            description=payload.description,
            knowledge_type=payload.knowledge_type,
            ownership_scope=payload.ownership_scope,
            status=payload.status,
            provenance=payload.provenance,
            imported_from=payload.imported_from,
            source_reference_id=payload.source_reference_id,
            actor_id=payload.actor_id,
        )
        session.commit()
        session.refresh(node)
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return KnowledgeNodeRead.model_validate(node)


@router.get("/nodes", response_model=list[KnowledgeNodeRead])
def list_knowledge_nodes_route(
    session: SessionDep,
    scope: Annotated[str, Query(min_length=1, description="Required ownership scope.")],
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[KnowledgeNodeRead]:
    """List nodes for one explicit scope."""
    try:
        nodes = list_knowledge_nodes(session, scope=scope, status=status_filter, limit=limit)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return [KnowledgeNodeRead.model_validate(node) for node in nodes]


@router.get("/nodes/{node_id}", response_model=KnowledgeNodeRead)
def get_knowledge_node_route(node_id: str, session: SessionDep) -> KnowledgeNodeRead:
    """Return one knowledge node by id."""
    node = get_knowledge_node(session, node_id)
    if node is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge node not found."
        )
    return KnowledgeNodeRead.model_validate(node)


@router.post(
    "/graph-references",
    response_model=GraphReferenceRead,
    status_code=status.HTTP_201_CREATED,
)
def create_graph_reference_route(
    payload: GraphReferenceCreate,
    session: SessionDep,
) -> GraphReferenceRead:
    """Create an explicit cross-scope graph reference."""
    try:
        reference = create_graph_reference(
            session,
            source_scope=payload.source_scope,
            target_scope=payload.target_scope,
            reason=payload.reason,
            actor_id=payload.actor_id,
        )
        session.commit()
        session.refresh(reference)
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return GraphReferenceRead.model_validate(reference)


@router.post("/edges", response_model=KnowledgeEdgeRead, status_code=status.HTTP_201_CREATED)
def create_knowledge_edge_route(
    payload: KnowledgeEdgeCreate,
    session: SessionDep,
) -> KnowledgeEdgeRead:
    """Create a knowledge edge and record an audit event."""
    try:
        edge = create_knowledge_edge(
            session,
            source_node_id=payload.source_node_id,
            target_node_id=payload.target_node_id,
            edge_type=payload.edge_type,
            confidence=payload.confidence,
            status=payload.status,
            provenance=payload.provenance,
            graph_reference_id=payload.graph_reference_id,
            actor_id=payload.actor_id,
        )
        session.commit()
        session.refresh(edge)
    except ValueError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return KnowledgeEdgeRead.model_validate(edge)


@router.get("/edges", response_model=list[KnowledgeEdgeRead])
def list_knowledge_edges_route(
    session: SessionDep,
    scope: Annotated[str, Query(min_length=1, description="Required ownership scope.")],
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[KnowledgeEdgeRead]:
    """List edges for one explicit scope."""
    try:
        edges = list_knowledge_edges(session, scope=scope, status=status_filter, limit=limit)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return [KnowledgeEdgeRead.model_validate(edge) for edge in edges]


@router.get("/edges/{edge_id}", response_model=KnowledgeEdgeRead)
def get_knowledge_edge_route(edge_id: str, session: SessionDep) -> KnowledgeEdgeRead:
    """Return one knowledge edge by id."""
    edge = get_knowledge_edge(session, edge_id)
    if edge is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge edge not found."
        )
    return KnowledgeEdgeRead.model_validate(edge)
