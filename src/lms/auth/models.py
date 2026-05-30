"""Authentication and identity SQLAlchemy models."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, String, func, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from lms.db.base import Base

if TYPE_CHECKING:
    from lms.learners.models import Learner


def new_uuid() -> str:
    """Return a string UUID suitable for database primary keys."""
    return str(uuid.uuid4())


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(UTC)


class User(Base):
    """Local-development user identity with SSO-ready stable identifiers."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    email: Mapped[str | None] = mapped_column(String(320), unique=True, index=True)
    username: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(200))
    is_local: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default=true(),
        nullable=False,
    )
    # Argon2 password hash for local login. Nullable so the existing local-dev
    # user (created via get_or_create_local_dev_user) can exist without a
    # password — that path is gated by ``Settings.auth_required`` being false.
    # Real users created via the bootstrap CLI will always have a hash set.
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        server_default=func.now(),
        nullable=False,
    )

    learners: Mapped[list[Learner]] = relationship(
        "Learner",
        back_populates="user",
        cascade="all, delete-orphan",
    )
