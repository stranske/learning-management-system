"""HTTP tests for the /knowledge graph CRUD surface."""

from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from lms.audit.models import AuditLog
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


def test_create_knowledge_node_records_audit_event(
    api_client: tuple[TestClient, Session],
) -> None:
    """POST /knowledge/nodes persists the node and audit trail."""
    client, session = api_client

    response = client.post(
        "/knowledge/nodes",
        json={
            "title": "Retrieval practice",
            "description": "Practice recalling material from memory.",
            "knowledge_type": "concept",
            "ownership_scope": "personal",
            "actor_id": "user:alice",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["ownership_scope"] == "personal"
    audit = session.query(AuditLog).filter_by(entity_id=payload["id"]).one()
    assert audit.entity_type == "KnowledgeNode"
    assert audit.action == "create"


def test_create_knowledge_edge_records_audit_event(
    api_client: tuple[TestClient, Session],
) -> None:
    """POST /knowledge/edges creates a same-scope edge and audit event."""
    client, session = api_client
    source = client.post(
        "/knowledge/nodes",
        json={
            "title": "Encoding",
            "knowledge_type": "concept",
            "ownership_scope": "personal",
            "actor_id": "user:alice",
        },
    ).json()
    target = client.post(
        "/knowledge/nodes",
        json={
            "title": "Retrieval",
            "knowledge_type": "concept",
            "ownership_scope": "personal",
            "actor_id": "user:alice",
        },
    ).json()

    response = client.post(
        "/knowledge/edges",
        json={
            "source_node_id": source["id"],
            "target_node_id": target["id"],
            "edge_type": "prerequisite",
            "confidence": 0.9,
            "actor_id": "user:alice",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["source_scope"] == "personal"
    assert payload["target_scope"] == "personal"
    audit = session.query(AuditLog).filter_by(entity_id=payload["id"]).one()
    assert audit.entity_type == "KnowledgeEdge"


def test_list_knowledge_nodes_requires_scope(api_client: tuple[TestClient, Session]) -> None:
    """GET /knowledge/nodes requires an explicit scope query parameter."""
    client, _session = api_client

    response = client.get("/knowledge/nodes")

    assert response.status_code == 422


def test_openapi_exposes_knowledge_paths(api_client: tuple[TestClient, Session]) -> None:
    """The graph CRUD surface appears in OpenAPI."""
    client, _session = api_client

    response = client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/knowledge/nodes" in paths
    assert "/knowledge/edges" in paths
