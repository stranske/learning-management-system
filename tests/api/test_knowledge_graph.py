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


def _post_node(
    client: TestClient,
    *,
    title: str,
    scope: str,
    knowledge_type: str = "conceptual",
) -> dict[str, object]:
    response = client.post(
        "/knowledge/nodes",
        json={
            "title": title,
            "knowledge_type": knowledge_type,
            "ownership_scope": scope,
            "actor_id": "user:alice",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_create_knowledge_node_records_audit_event(
    api_client: tuple[TestClient, Session],
) -> None:
    """POST /knowledge/nodes persists the row and the audit trail."""
    client, session = api_client
    payload = _post_node(client, title="Spaced retrieval", scope="personal")

    assert payload["status"] == "draft"
    assert payload["ownership_scope"] == "personal"

    audit = session.query(AuditLog).filter_by(entity_id=payload["id"]).one()
    assert audit.entity_type == "KnowledgeNode"
    assert audit.action == "create"
    assert audit.actor_id == "user:alice"


def test_create_prerequisite_edge_records_audit_event(
    api_client: tuple[TestClient, Session],
) -> None:
    """POST /knowledge/edges persists the row and the audit trail."""
    client, session = api_client
    parent = _post_node(client, title="Long-term memory", scope="personal")
    child = _post_node(client, title="Retrieval practice", scope="personal")

    response = client.post(
        "/knowledge/edges",
        json={
            "source_node_id": parent["id"],
            "target_node_id": child["id"],
            "edge_type": "prerequisite",
            "ownership_scope": "personal",
            "actor_id": "user:alice",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["source_scope"] == "personal"
    assert body["target_scope"] == "personal"
    assert body["is_graph_reference"] is False

    audit = session.query(AuditLog).filter_by(entity_id=body["id"]).one()
    assert audit.entity_type == "KnowledgeEdge"
    assert audit.action == "create"


def test_create_edge_rejects_implicit_cross_scope(
    api_client: tuple[TestClient, Session],
) -> None:
    """POST /knowledge/edges refuses cross-scope edges without is_graph_reference."""
    client, _session = api_client
    personal = _post_node(client, title="Personal goal", scope="personal")
    institutional = _post_node(client, title="Institutional concept", scope="institutional")

    response = client.post(
        "/knowledge/edges",
        json={
            "source_node_id": personal["id"],
            "target_node_id": institutional["id"],
            "edge_type": "prerequisite",
            "ownership_scope": "personal",
            "target_scope": "institutional",
            "is_graph_reference": False,
            "actor_id": "user:alice",
        },
    )
    assert response.status_code == 422
    assert "is_graph_reference" in response.json()["detail"]


def test_list_nodes_requires_scope_query(
    api_client: tuple[TestClient, Session],
) -> None:
    """GET /knowledge/nodes refuses requests without an explicit scope."""
    client, _session = api_client
    response = client.get("/knowledge/nodes")
    assert response.status_code == 422


def test_list_nodes_is_scope_pure(api_client: tuple[TestClient, Session]) -> None:
    """GET /knowledge/nodes returns only rows for the requested scope."""
    client, _session = api_client
    _post_node(client, title="Personal node", scope="personal")
    _post_node(client, title="Institutional node", scope="institutional")

    personal = client.get("/knowledge/nodes", params={"scope": "personal"})
    institutional = client.get("/knowledge/nodes", params={"scope": "institutional"})

    assert personal.status_code == 200
    assert institutional.status_code == 200
    assert [item["title"] for item in personal.json()] == ["Personal node"]
    assert [item["title"] for item in institutional.json()] == ["Institutional node"]


def test_openapi_exposes_knowledge_graph_paths(
    api_client: tuple[TestClient, Session],
) -> None:
    """The /knowledge graph CRUD surface appears in OpenAPI."""
    client, _session = api_client
    response = client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/knowledge/nodes" in paths
    assert "/knowledge/edges" in paths
