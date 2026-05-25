"""HTTP tests for the /audit/events read endpoint."""

from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from lms.audit.repository import record_audit_event
from lms.db.base import Base
from lms.db.session import get_session
from lms.main import create_app


@pytest.fixture
def api_client() -> Generator[tuple[TestClient, Session], None, None]:
    """Provide a FastAPI test client backed by a shared in-memory SQLite engine."""
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

    def override_get_session() -> Generator[Session, None, None]:
        request_session = session_factory()
        try:
            yield request_session
        finally:
            request_session.close()

    app = create_app()
    app.dependency_overrides[get_session] = override_get_session

    try:
        with TestClient(app) as client:
            yield client, session
    finally:
        session.close()
        app.dependency_overrides.clear()
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
    api_client: tuple[TestClient, Session],
) -> None:
    """GET /audit/events?entity_type=SourceReference returns only matching events."""
    client, session = api_client
    _seed_three_events(session)

    response = client.get("/audit/events", params={"entity_type": "SourceReference"})

    assert response.status_code == 200
    payload = response.json()
    assert {event["entity_type"] for event in payload} == {"SourceReference"}
    assert len(payload) == 2


def test_audit_events_endpoint_filters_by_actor(
    api_client: tuple[TestClient, Session],
) -> None:
    """GET /audit/events?actor_id=user:bob returns only bob's events."""
    client, session = api_client
    _seed_three_events(session)

    response = client.get("/audit/events", params={"actor_id": "user:bob"})

    assert response.status_code == 200
    payload = response.json()
    assert [event["actor_id"] for event in payload] == ["user:bob"]


def test_audit_events_endpoint_returns_all_when_unfiltered(
    api_client: tuple[TestClient, Session],
) -> None:
    """GET /audit/events without filters returns every recorded event."""
    client, session = api_client
    _seed_three_events(session)

    response = client.get("/audit/events")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 3


def test_audit_events_endpoint_rejects_invalid_limit(
    api_client: tuple[TestClient, Session],
) -> None:
    """Limits below 1 are rejected by the FastAPI query validator."""
    client, _session = api_client

    response = client.get("/audit/events", params={"limit": 0})

    assert response.status_code == 422


def test_openapi_exposes_audit_events_path(api_client: tuple[TestClient, Session]) -> None:
    """The /audit/events path appears in the OpenAPI schema."""
    client, _session = api_client

    response = client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/audit/events" in paths
