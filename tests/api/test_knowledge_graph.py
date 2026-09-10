"""HTTP tests for the /knowledge graph CRUD surface."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from lms.audit.models import AuditLog
from lms.db.base import Base
from lms.db.session import get_session
from lms.graphs.repository import ORDERING_EDGE_TYPES
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
) -> dict[str, Any]:
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
    return cast(dict[str, Any], response.json())


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


def test_get_node_returns_404_for_unknown_id(
    api_client: tuple[TestClient, Session],
) -> None:
    """GET /knowledge/nodes/{id} returns 404 when the node does not exist."""
    client, _session = api_client
    response = client.get("/knowledge/nodes/does-not-exist", params={"scope": "personal"})
    assert response.status_code == 404


def test_get_node_returns_404_for_wrong_scope(
    api_client: tuple[TestClient, Session],
) -> None:
    """GET /knowledge/nodes/{id} returns 404 when the node is in a different scope."""
    client, _session = api_client
    node = _post_node(client, title="Institutional only", scope="institutional")
    response = client.get(f"/knowledge/nodes/{node['id']}", params={"scope": "personal"})
    assert response.status_code == 404


def test_update_node_route_changes_title(api_client: tuple[TestClient, Session]) -> None:
    """PATCH /knowledge/nodes/{id} updates mutable fields and returns updated data."""
    client, _session = api_client
    node = _post_node(client, title="Before", scope="personal")

    response = client.patch(
        f"/knowledge/nodes/{node['id']}",
        params={"scope": "personal"},
        json={"title": "After", "actor_id": "user:alice"},
    )
    assert response.status_code == 200
    assert response.json()["title"] == "After"


def test_update_node_route_returns_404_for_missing(
    api_client: tuple[TestClient, Session],
) -> None:
    """PATCH /knowledge/nodes/{id} returns 404 when the node does not exist."""
    client, _session = api_client
    response = client.patch(
        "/knowledge/nodes/ghost",
        params={"scope": "personal"},
        json={"title": "Noop", "actor_id": "user:alice"},
    )
    assert response.status_code == 404


def test_delete_node_route_removes_node(api_client: tuple[TestClient, Session]) -> None:
    """DELETE /knowledge/nodes/{id} removes the node and returns 204."""
    client, _session = api_client
    node = _post_node(client, title="Delete me", scope="personal")

    response = client.delete(f"/knowledge/nodes/{node['id']}", params={"scope": "personal"})
    assert response.status_code == 204

    get_response = client.get(f"/knowledge/nodes/{node['id']}", params={"scope": "personal"})
    assert get_response.status_code == 404


def test_delete_node_route_returns_404_for_missing(
    api_client: tuple[TestClient, Session],
) -> None:
    """DELETE /knowledge/nodes/{id} returns 404 when the node does not exist."""
    client, _session = api_client
    response = client.delete("/knowledge/nodes/ghost", params={"scope": "personal"})
    assert response.status_code == 404


def test_list_edges_with_filters(api_client: tuple[TestClient, Session]) -> None:
    """GET /knowledge/edges applies edge_type, status, and node-id filters."""
    client, _session = api_client
    parent = _post_node(client, title="Parent", scope="personal")
    child = _post_node(client, title="Child", scope="personal")
    parent_id = cast(str, parent["id"])
    child_id = cast(str, child["id"])
    response = client.post(
        "/knowledge/edges",
        json={
            "source_node_id": parent_id,
            "target_node_id": child_id,
            "edge_type": "analogy",
            "ownership_scope": "personal",
            "actor_id": "user:alice",
        },
    )
    assert response.status_code == 201
    edge_id = response.json()["id"]

    by_type = client.get(
        "/knowledge/edges",
        params={"scope": "personal", "edge_type": "analogy"},
    )
    assert by_type.status_code == 200
    assert any(e["id"] == edge_id for e in by_type.json())

    by_source = client.get(
        "/knowledge/edges",
        params={"scope": "personal", "source_node_id": parent_id},
    )
    assert by_source.status_code == 200
    assert any(e["id"] == edge_id for e in by_source.json())

    by_target = client.get(
        "/knowledge/edges",
        params={"scope": "personal", "target_node_id": child_id},
    )
    assert by_target.status_code == 200
    assert any(e["id"] == edge_id for e in by_target.json())


def test_get_edge_returns_404_for_unknown_id(
    api_client: tuple[TestClient, Session],
) -> None:
    """GET /knowledge/edges/{id} returns 404 when the edge does not exist."""
    client, _session = api_client
    response = client.get("/knowledge/edges/does-not-exist", params={"scope": "personal"})
    assert response.status_code == 404


def test_delete_edge_route_removes_edge(api_client: tuple[TestClient, Session]) -> None:
    """DELETE /knowledge/edges/{id} removes the edge and returns 204."""
    client, _session = api_client
    parent = _post_node(client, title="Parent", scope="personal")
    child = _post_node(client, title="Child", scope="personal")
    edge_response = client.post(
        "/knowledge/edges",
        json={
            "source_node_id": parent["id"],
            "target_node_id": child["id"],
            "edge_type": "prerequisite",
            "ownership_scope": "personal",
            "actor_id": "user:alice",
        },
    )
    assert edge_response.status_code == 201
    edge_id = edge_response.json()["id"]

    response = client.delete(f"/knowledge/edges/{edge_id}", params={"scope": "personal"})
    assert response.status_code == 204

    get_response = client.get(f"/knowledge/edges/{edge_id}", params={"scope": "personal"})
    assert get_response.status_code == 404


def test_delete_edge_route_returns_404_for_missing(
    api_client: tuple[TestClient, Session],
) -> None:
    """DELETE /knowledge/edges/{id} returns 404 when the edge does not exist."""
    client, _session = api_client
    response = client.delete("/knowledge/edges/ghost", params={"scope": "personal"})
    assert response.status_code == 404


def _post_edge(client: TestClient, source: str, target: str, edge_type: str) -> dict[str, Any]:
    response = client.post(
        "/knowledge/edges",
        json={
            "source_node_id": source,
            "target_node_id": target,
            "edge_type": edge_type,
            "ownership_scope": "personal",
            "actor_id": "user:alice",
            "notes": "original",
        },
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


@pytest.mark.parametrize("edge_type", ORDERING_EDGE_TYPES)
@pytest.mark.parametrize("path_length", [2, 3])
def test_patch_edge_rejects_ordering_cycle(
    api_client: tuple[TestClient, Session], edge_type: str, path_length: int
) -> None:
    """PATCH returns 422 without changing persisted edge fields or its audit trail."""
    client, session = api_client
    nodes = [_post_node(client, title=f"Node {i}", scope="personal") for i in range(path_length)]
    for index, (source, target) in enumerate(zip(nodes, nodes[1:], strict=False)):
        _post_edge(client, source["id"], target["id"], ORDERING_EDGE_TYPES[index])
    edge = _post_edge(client, nodes[-1]["id"], nodes[0]["id"], "analogy")
    response = client.patch(
        f"/knowledge/edges/{edge['id']}",
        params={"scope": "personal"},
        json={"notes": "must not persist", "edge_type": edge_type},
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"] == "edge would create a prerequisite cycle"
    persisted = client.get(f"/knowledge/edges/{edge['id']}", params={"scope": "personal"})
    assert persisted.json() == edge
    assert session.query(AuditLog).filter_by(entity_id=edge["id"]).count() == 1
    # Rejection must not prevent a later legitimate edit of the non-ordering edge.
    response = client.patch(
        f"/knowledge/edges/{edge['id']}",
        params={"scope": "personal"},
        json={"status": "published", "edge_type": "contrast", "actor_id": "user:bob"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["edge_type"] == "contrast"
    audit = session.query(AuditLog).filter_by(entity_id=edge["id"], action="update").one()
    assert audit.actor_id == "user:bob"
    assert audit.before_summary is not None and audit.after_summary is not None
    assert audit.before_summary["edge_type"] == "analogy"
    assert audit.after_summary["edge_type"] == "contrast"


@pytest.mark.parametrize("edge_type", ORDERING_EDGE_TYPES)
def test_patch_edge_accepts_acyclic_ordering_update(
    api_client: tuple[TestClient, Session], edge_type: str
) -> None:
    """The HTTP path accepts a valid ordering edge type and preserves its endpoints."""
    client, session = api_client
    a = _post_node(client, title="A", scope="personal")
    b = _post_node(client, title="B", scope="personal")
    edge = _post_edge(client, a["id"], b["id"], "analogy")
    response = client.patch(
        f"/knowledge/edges/{edge['id']}",
        params={"scope": "personal"},
        json={"edge_type": edge_type, "confidence": 0.7},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["edge_type"], body["confidence"]) == (edge_type, 0.7)
    assert (body["source_node_id"], body["target_node_id"]) == (a["id"], b["id"])
    assert session.query(AuditLog).filter_by(entity_id=edge["id"], action="update").count() == 1


def test_patch_edge_requires_scope_and_hides_other_scope(
    api_client: tuple[TestClient, Session],
) -> None:
    """Edge mutation follows the same required scope boundary as graph reads."""
    client, session = api_client
    a = _post_node(client, title="A", scope="personal")
    b = _post_node(client, title="B", scope="personal")
    edge = _post_edge(client, a["id"], b["id"], "analogy")
    url = f"/knowledge/edges/{edge['id']}"
    assert client.patch(url, json={"notes": "no scope"}).status_code == 422
    assert (
        client.patch(
            url, params={"scope": "institutional"}, json={"notes": "wrong scope"}
        ).status_code
        == 404
    )
    assert (
        client.patch(
            "/knowledge/edges/missing", params={"scope": "personal"}, json={"notes": "missing"}
        ).status_code
        == 404
    )
    persisted = client.get(url, params={"scope": "personal"})
    assert persisted.json() == edge
    assert session.query(AuditLog).filter_by(entity_id=edge["id"]).count() == 1
