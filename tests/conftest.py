"""Shared pytest fixtures for LMS tests."""

from __future__ import annotations

from collections.abc import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import lms.audit.models  # noqa: F401  # register Base.metadata
import lms.evidence.models  # noqa: F401  # register Base.metadata
import lms.graphs.models  # noqa: F401  # register Base.metadata
import lms.learners.models  # noqa: F401  # register Base.metadata
import lms.llm.models  # noqa: F401  # register Base.metadata
import lms.prompts.models  # noqa: F401  # register Base.metadata
import lms.scheduling.models  # noqa: F401  # register Base.metadata
import lms.sources.models  # noqa: F401  # register Base.metadata
from lms.db.base import Base


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    """Provide an isolated SQLAlchemy session for model-level tests."""
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()
