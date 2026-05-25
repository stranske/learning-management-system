"""HTTP CRUD routes for knowledge graph nodes and edges."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from lms.db.session import get_session
from lms.graphs.repository import (
    create_knowledge_edge,
    create_knowledge_node,
    delete_knowledge_edge,
    delete_knowledge_node,
    get_knowledge_edge,
    get_knowledge_node,
    list_knowledge_edges,
    list_knowledge_nodes,
    update_knowledge_node,
)
from lms.graphs.schemas import (
    EdgeStatus,
    EdgeType,
    KnowledgeEdgeCreate,
    KnowledgeEdgeRead,
    KnowledgeNodeCreate,
    KnowledgeNodeRead,
    KnowledgeNodeUpdate,
    KnowledgeType,
    NodeStatus,
    OwnershipScope,
)

router = APIRouter(prefix="/knowledge", tags=["knowledge-graph"])
SessionDep = Annotated[Session, Depends(get_session)]
ScopeQuery = Annotated[
    OwnershipScope,
    Query(
        description=(
            "Required ownership scope (personal or institutional); reads and "
            "writes are scope-pure by default."
        ),
    ),
]


@router.post(
    "/nodes",
    response_model=KnowledgeNodeRead,
    status_code=status.HTTP_201_CREATED,
)
def create_node_route(
    payload: KnowledgeNodeCreate,
    session: SessionDep,
) -> KnowledgeNodeRead:
    """Create a knowledge node and record an audit event."""
    try:
        node = create_knowledge_node(
            session,
            title=payload.title,
            knowledge_type=payload.knowledge_type,
            scope=payload.ownership_scope,
            actor_id=payload.actor_id,
            description=payload.description,
            status=payload.status,
            provenance=payload.provenance,
            imported_from=payload.imported_from,
            source_reference_id=payload.source_reference_id,
            source_subsystem="api",
        )
        session.commit()
        session.refresh(node)
    except ValueError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return KnowledgeNodeRead.model_validate(node)


@router.get("/nodes", response_model=list[KnowledgeNodeRead])
def list_nodes_route(
    session: SessionDep,
    scope: ScopeQuery,
    knowledge_type: Annotated[
        KnowledgeType | None, Query(description="Filter by knowledge type.")
    ] = None,
    node_status: Annotated[
        NodeStatus | None,
        Query(alias="status", description="Filter by node status."),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[KnowledgeNodeRead]:
    """Return knowledge nodes for the given ownership scope."""
    nodes = list_knowledge_nodes(
        session,
        scope=scope,
        status=node_status,
        knowledge_type=knowledge_type,
        limit=limit,
    )
    return [KnowledgeNodeRead.model_validate(node) for node in nodes]


@router.get("/nodes/{node_id}", response_model=KnowledgeNodeRead)
def get_node_route(
    node_id: str,
    session: SessionDep,
    scope: ScopeQuery,
) -> KnowledgeNodeRead:
    """Return one node by id within the requested ownership scope."""
    node = get_knowledge_node(session, node_id, scope=scope)
    if node is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge node not found in this scope.",
        )
    return KnowledgeNodeRead.model_validate(node)


@router.patch("/nodes/{node_id}", response_model=KnowledgeNodeRead)
def update_node_route(
    node_id: str,
    payload: KnowledgeNodeUpdate,
    session: SessionDep,
    scope: ScopeQuery,
) -> KnowledgeNodeRead:
    """Update a node and record an audit event."""
    node = get_knowledge_node(session, node_id, scope=scope)
    if node is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge node not found in this scope.",
        )
    changes = payload.model_dump(exclude={"actor_id"}, exclude_none=True)
    try:
        updated = update_knowledge_node(
            session,
            node,
            actor_id=payload.actor_id,
            **changes,
        )
        session.commit()
        session.refresh(updated)
    except ValueError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return KnowledgeNodeRead.model_validate(updated)


@router.delete("/nodes/{node_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_node_route(
    node_id: str,
    session: SessionDep,
    scope: ScopeQuery,
    actor_id: Annotated[str, Query(min_length=1, max_length=255)] = "system:api",
) -> Response:
    """Delete a node within the requested ownership scope."""
    node = get_knowledge_node(session, node_id, scope=scope)
    if node is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge node not found in this scope.",
        )
    delete_knowledge_node(session, node, actor_id=actor_id)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/edges",
    response_model=KnowledgeEdgeRead,
    status_code=status.HTTP_201_CREATED,
)
def create_edge_route(
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
            scope=payload.ownership_scope,
            target_scope=payload.target_scope,
            is_graph_reference=payload.is_graph_reference,
            confidence=payload.confidence,
            status=payload.status,
            notes=payload.notes,
            actor_id=payload.actor_id,
            source_subsystem="api",
        )
        session.commit()
        session.refresh(edge)
    except ValueError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return KnowledgeEdgeRead.model_validate(edge)


@router.get("/edges", response_model=list[KnowledgeEdgeRead])
def list_edges_route(
    session: SessionDep,
    scope: ScopeQuery,
    edge_type: Annotated[EdgeType | None, Query(description="Filter by edge type.")] = None,
    edge_status: Annotated[
        EdgeStatus | None,
        Query(alias="status", description="Filter by edge status."),
    ] = None,
    source_node_id: Annotated[
        str | None,
        Query(min_length=1, max_length=36, description="Filter by source node id."),
    ] = None,
    target_node_id: Annotated[
        str | None,
        Query(min_length=1, max_length=36, description="Filter by target node id."),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[KnowledgeEdgeRead]:
    """Return knowledge edges anchored on the given source-side scope."""
    edges = list_knowledge_edges(
        session,
        scope=scope,
        edge_type=edge_type,
        status=edge_status,
        source_node_id=source_node_id,
        target_node_id=target_node_id,
        limit=limit,
    )
    return [KnowledgeEdgeRead.model_validate(edge) for edge in edges]


@router.get("/edges/{edge_id}", response_model=KnowledgeEdgeRead)
def get_edge_route(
    edge_id: str,
    session: SessionDep,
    scope: ScopeQuery,
) -> KnowledgeEdgeRead:
    """Return one edge by id within the requested ownership scope."""
    edge = get_knowledge_edge(session, edge_id, scope=scope)
    if edge is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge edge not found in this scope.",
        )
    return KnowledgeEdgeRead.model_validate(edge)


@router.delete("/edges/{edge_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_edge_route(
    edge_id: str,
    session: SessionDep,
    scope: ScopeQuery,
    actor_id: Annotated[str, Query(min_length=1, max_length=255)] = "system:api",
) -> Response:
    """Delete an edge within the requested ownership scope."""
    edge = get_knowledge_edge(session, edge_id, scope=scope)
    if edge is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge edge not found in this scope.",
        )
    delete_knowledge_edge(session, edge, actor_id=actor_id)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
