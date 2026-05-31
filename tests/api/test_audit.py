"""Unit tests for the audit read endpoint logic without HTTP transport."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from lms.api.audit import read_audit_events
from lms.audit.repository import record_audit_event
from lms.db.base import Base


def _session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )


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


def test_read_audit_events_filters_by_entity_type() -> None:
    """Endpoint helper returns only matching entity types when filtered."""
    session = _session_factory()()
    _seed_three_events(session)

    payload = read_audit_events(session, entity_type="SourceReference")

    assert {event.entity_type for event in payload} == {"SourceReference"}
    assert len(payload) == 2


def test_read_audit_events_filters_by_actor() -> None:
    """Endpoint helper returns only the requested actor's records."""
    session = _session_factory()()
    _seed_three_events(session)

    payload = read_audit_events(session, actor_id="user:bob")

    assert [event.actor_id for event in payload] == ["user:bob"]


def test_read_audit_events_returns_all_when_unfiltered() -> None:
    """Endpoint helper returns all records when no filters are supplied."""
    session = _session_factory()()
    _seed_three_events(session)

    payload = read_audit_events(session)

    assert len(payload) == 3


def test_read_audit_events_applies_limit() -> None:
    """Endpoint helper honors the explicit limit argument."""
    session = _session_factory()()
    _seed_three_events(session)

    payload = read_audit_events(session, limit=1)

    assert len(payload) == 1
