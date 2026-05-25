"""SQLAlchemy model for source-grounded prompt and importer references."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from lms.auth.models import new_uuid, utc_now
from lms.db.base import Base

if TYPE_CHECKING:
    from lms.prompts.models import Prompt

SOURCE_TYPES: tuple[str, ...] = (
    "markdown-file",
    "kindle-highlight",
    "url",
    "pdf-passage",
    "internal-note",
)
SOURCE_VISIBILITIES: tuple[str, ...] = ("public", "local-only")
DRIFT_STATUSES: tuple[str, ...] = ("current", "stale", "missing")
MULTI_SOURCE_ROLES: tuple[str, ...] = ("primary", "supporting", "counterpoint")


def _sql_values(values: tuple[str, ...]) -> str:
    """Return SQL string literals for a check constraint."""
    return ", ".join(f"'{value}'" for value in values)


class SourceReference(Base):
    """A stable citation target used by prompts, importers, and drift checks."""

    __tablename__ = "source_references"
    __table_args__ = (
        CheckConstraint(
            f"source_type IN ({_sql_values(SOURCE_TYPES)})",
            name="source_type_valid",
        ),
        CheckConstraint(
            f"source_visibility IN ({_sql_values(SOURCE_VISIBILITIES)})",
            name="source_visibility_valid",
        ),
        CheckConstraint(
            f"drift_status IN ({_sql_values(DRIFT_STATUSES)})",
            name="drift_status_valid",
        ),
        CheckConstraint(
            f"multi_source_role IS NULL OR multi_source_role IN ({_sql_values(MULTI_SOURCE_ROLES)})",
            name="multi_source_role_valid",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    stable_locator: Mapped[str] = mapped_column(String(1024), nullable=False, index=True)
    passage_range: Mapped[str | None] = mapped_column(String(120))
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    hash_algorithm: Mapped[str] = mapped_column(String(32), default="sha256", nullable=False)
    source_visibility: Mapped[str] = mapped_column(String(32), default="public", nullable=False)
    drift_status: Mapped[str] = mapped_column(
        String(32), default="current", nullable=False, index=True
    )
    multi_source_role: Mapped[str | None] = mapped_column(String(32))
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        nullable=False,
        index=True,
    )
    prompts: Mapped[list[Prompt]] = relationship(
        "Prompt",
        secondary="prompt_source_references",
        back_populates="source_references",
    )
