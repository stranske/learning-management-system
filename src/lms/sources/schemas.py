"""Pydantic schemas for the SourceReference HTTP surface."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SourceType = Literal["markdown-file", "kindle-highlight", "url", "pdf-passage", "internal-note"]
SourceVisibility = Literal["public", "local-only"]
DriftStatus = Literal["current", "stale", "missing"]
MultiSourceRole = Literal["primary", "supporting", "counterpoint"]


class SourceReferenceCreate(BaseModel):
    """Input for creating a source reference."""

    source_type: SourceType
    stable_locator: str = Field(min_length=1, max_length=1024)
    passage_range: str | None = Field(default=None, max_length=120)
    content: str | None = Field(default=None, exclude=True)
    content_hash: str | None = Field(default=None, max_length=128)
    hash_algorithm: str = Field(default="sha256", max_length=32)
    source_visibility: SourceVisibility = "public"
    multi_source_role: MultiSourceRole | None = None
    actor_id: str = Field(default="system:api", min_length=1, max_length=255)


class SourceReferenceUpdate(BaseModel):
    """Input for updating a source reference."""

    stable_locator: str | None = Field(default=None, min_length=1, max_length=1024)
    passage_range: str | None = Field(default=None, max_length=120)
    content: str | None = Field(default=None, exclude=True)
    content_hash: str | None = Field(default=None, max_length=128)
    source_visibility: SourceVisibility | None = None
    drift_status: DriftStatus | None = None
    multi_source_role: MultiSourceRole | None = None
    actor_id: str = Field(default="system:api", min_length=1, max_length=255)


class SourceReferenceRead(BaseModel):
    """Serializable source reference."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    source_type: str
    stable_locator: str
    passage_range: str | None
    content_hash: str
    hash_algorithm: str
    source_visibility: str
    drift_status: str
    multi_source_role: str | None
    captured_at: datetime
