"""API-layer tests for the audit events read surface."""

from __future__ import annotations

from collections.abc import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from lms.api.audit import read_audit_events
from lms.audit.repository import record_audit_event
from lms.db.base import Base
from lms.main import create_app


@pytest.fixture
def session_factory() -> Generator[sessionmaker[Session], None, None]:
    """Provide a shared in-memory SQLite session factory."""
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
    try:
        yield session_factory
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def _seed_three_events(session: Session) -> None:
    record_audit_event(
        session,
        actor_id="user:alice",
        action="create",
        entity_type="SourceReference",
        entity_id="src-001",
        source_subsystem="research-importer",
        after_summary={"title": "Quantum Mechanics, 3e"},
    )
    record_audit_event(
        session,
        actor_id="user:bob",
        action="create",
        entity_type="KnowledgeNode",
        entity_id="node-001",
        source_subsystem="graph-importer",
    )
    record_audit_event(
        session,
        actor_id="user:alice",
        action="update",
        entity_type="SourceReference",
        entity_id="src-001",
        source_subsystem="research-importer",
        before_summary={"title": "Quantum Mechanics, 3e"},
        after_summary={"title": "Quantum Mechanics, 3e (reprint)"},
    )
    session.commit()


def test_audit_events_endpoint_filters_by_entity_type(
    session_factory: sessionmaker[Session],
) -> None:
    """SourceReference filter returns only SourceReference events."""
    with session_factory() as session:
        _seed_three_events(session)
        payload = read_audit_events(session, entity_type="SourceReference")
    assert {event.entity_type for event in payload} == {"SourceReference"}
    assert len(payload) == 2


def test_audit_events_endpoint_filters_by_actor(
    session_factory: sessionmaker[Session],
) -> None:
    """Actor filter returns only the matching actor's events."""
    with session_factory() as session:
        _seed_three_events(session)
        payload = read_audit_events(session, actor_id="user:bob")
    assert [event.actor_id for event in payload] == ["user:bob"]


def test_audit_events_endpoint_returns_all_when_unfiltered(
    session_factory: sessionmaker[Session],
) -> None:
    """Unfiltered reads return all recorded events."""
    with session_factory() as session:
        _seed_three_events(session)
        payload = read_audit_events(session)
    assert len(payload) == 3


def test_audit_events_endpoint_limit_is_applied(session_factory: sessionmaker[Session]) -> None:
    """Limit parameter trims returned events."""
    with session_factory() as session:
        _seed_three_events(session)
        payload = read_audit_events(session, limit=2)
    assert len(payload) == 2


def test_openapi_exposes_audit_events_path() -> None:
    """The /audit/events path appears in the OpenAPI schema."""
    app = create_app()
    paths = app.openapi()["paths"]
    assert "/audit/events" in paths
