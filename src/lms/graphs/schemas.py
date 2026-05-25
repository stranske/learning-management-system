"""Pydantic schemas for the knowledge graph API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

KnowledgeType = Literal["concept", "fact", "procedure", "principle", "question"]
OwnershipScope = Literal["personal", "institutional"]
KnowledgeStatus = Literal["draft", "published", "archived"]
EdgeType = Literal["prerequisite", "supports", "contradicts", "cross-scope-reference"]
EdgeStatus = Literal["draft", "active", "archived"]


class KnowledgeNodeCreate(BaseModel):
    """Input for creating a scoped knowledge node."""

    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2048)
    knowledge_type: KnowledgeType
    ownership_scope: OwnershipScope
    status: KnowledgeStatus = "draft"
    provenance: dict[str, Any] | None = None
    imported_from: str | None = Field(default=None, max_length=1024)
    source_reference_id: str | None = None
    actor_id: str = Field(default="system:api", min_length=1, max_length=255)


class KnowledgeNodeRead(BaseModel):
    """Serializable knowledge node."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    description: str | None
    knowledge_type: str
    ownership_scope: str
    status: str
    provenance: dict[str, Any] | None
    imported_from: str | None
    source_reference_id: str | None
    created_at: datetime
    updated_at: datetime


class GraphReferenceCreate(BaseModel):
    """Input for explicitly authorizing a cross-scope edge."""

    source_scope: OwnershipScope
    target_scope: OwnershipScope
    reason: str = Field(min_length=1, max_length=1024)
    actor_id: str = Field(default="system:api", min_length=1, max_length=255)


class GraphReferenceRead(BaseModel):
    """Serializable graph reference."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    source_scope: str
    target_scope: str
    reason: str
    actor_id: str
    created_at: datetime


class KnowledgeEdgeCreate(BaseModel):
    """Input for creating a typed edge between two nodes."""

    source_node_id: str
    target_node_id: str
    edge_type: EdgeType
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    status: EdgeStatus = "draft"
    provenance: dict[str, Any] | None = None
    graph_reference_id: str | None = None
    actor_id: str = Field(default="system:api", min_length=1, max_length=255)


class KnowledgeEdgeRead(BaseModel):
    """Serializable knowledge edge."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    source_node_id: str
    target_node_id: str
    edge_type: str
    ownership_scope: str
    source_scope: str
    target_scope: str
    confidence: float | None
    status: str
    provenance: dict[str, Any] | None
    graph_reference_id: str | None
    created_by: str
    updated_by: str
    created_at: datetime
    updated_at: datetime
