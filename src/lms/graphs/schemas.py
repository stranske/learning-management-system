"""Pydantic schemas for the /knowledge graph HTTP surface."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

KnowledgeType = Literal[
    "factual",
    "conceptual",
    "procedural",
    "judgment",
    "metacognitive",
    "social",
    "compliance",
]
OwnershipScope = Literal["personal", "institutional"]
NodeStatus = Literal["draft", "published", "deprecated"]
NodeProvenance = Literal["manual", "imported", "llm-proposed"]
EdgeType = Literal[
    "prerequisite",
    "key-prerequisite",
    "encompassing",
    "interference-risk",
    "analogy",
    "contrast",
    "transfer-context",
    "supports-competency",
]
EdgeStatus = Literal["draft", "published", "deprecated"]


class KnowledgeNodeCreate(BaseModel):
    """Input for creating a knowledge node."""

    title: str = Field(min_length=1, max_length=255)
    knowledge_type: KnowledgeType
    ownership_scope: OwnershipScope
    description: str | None = None
    status: NodeStatus = "draft"
    provenance: NodeProvenance = "manual"
    imported_from: str | None = Field(default=None, max_length=1024)
    source_reference_id: str | None = Field(default=None, max_length=36)
    actor_id: str = Field(default="system:api", min_length=1, max_length=255)


class KnowledgeNodeUpdate(BaseModel):
    """Input for updating a knowledge node (ownership_scope is immutable)."""

    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    knowledge_type: KnowledgeType | None = None
    status: NodeStatus | None = None
    provenance: NodeProvenance | None = None
    imported_from: str | None = Field(default=None, max_length=1024)
    source_reference_id: str | None = Field(default=None, max_length=36)
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
    provenance: str
    imported_from: str | None
    source_reference_id: str | None
    created_at: datetime
    updated_at: datetime


class KnowledgeEdgeCreate(BaseModel):
    """Input for creating a knowledge edge."""

    source_node_id: str = Field(min_length=1, max_length=36)
    target_node_id: str = Field(min_length=1, max_length=36)
    edge_type: EdgeType = "prerequisite"
    ownership_scope: OwnershipScope
    target_scope: OwnershipScope | None = None
    is_graph_reference: bool = False
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    status: EdgeStatus = "draft"
    notes: str | None = None
    actor_id: str = Field(default="system:api", min_length=1, max_length=255)


class KnowledgeEdgeRead(BaseModel):
    """Serializable knowledge edge."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    source_node_id: str
    target_node_id: str
    edge_type: str
    source_scope: str
    target_scope: str
    is_graph_reference: bool
    confidence: float | None
    status: str
    notes: str | None
    created_at: datetime
    updated_at: datetime
