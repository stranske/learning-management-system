"""HTTP tests for the /source-references CRUD surface."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

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


def test_create_source_reference_records_audit_event(
    api_client: tuple[TestClient, Session],
) -> None:
    """POST /source-references persists the row and the audit trail."""
    client, session = api_client

    response = client.post(
        "/source-references",
        json={
            "source_type": "internal-note",
            "stable_locator": "note:source-citation-policy",
            "content": "Every prompt carries at least one source reference.",
            "source_visibility": "local-only",
            "multi_source_role": "primary",
            "actor_id": "user:alice",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["source_type"] == "internal-note"
    assert payload["drift_status"] == "current"
    audit = session.query(AuditLog).filter_by(entity_id=payload["id"]).one()
    assert audit.entity_type == "SourceReference"
    assert audit.action == "create"
    assert audit.actor_id == "user:alice"


def test_openapi_exposes_source_reference_paths(
    api_client: tuple[TestClient, Session],
) -> None:
    """The SourceReference CRUD surface appears in OpenAPI."""
    client, _session = api_client

    response = client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/source-references" in paths


def test_create_markdown_file_reference_requires_client_supplied_hash(
    api_client: tuple[TestClient, Session],
    tmp_path: Path,
) -> None:
    """POST rejects markdown-file references without content/content_hash."""
    client, session = api_client
    target = tmp_path / "secret.md"
    target.write_text("sensitive\n", encoding="utf-8")

    response = client.post(
        "/source-references",
        json={
            "source_type": "markdown-file",
            "stable_locator": str(target),
            "actor_id": "user:attacker",
        },
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "markdown-file" in detail
    assert session.query(AuditLog).count() == 0


def test_create_markdown_file_reference_accepts_client_supplied_hash(
    api_client: tuple[TestClient, Session],
) -> None:
    """POST accepts markdown-file references when caller supplies content_hash."""
    client, session = api_client

    response = client.post(
        "/source-references",
        json={
            "source_type": "markdown-file",
            "stable_locator": "docs/research/citation.md",
            "content_hash": "0" * 64,
            "actor_id": "user:alice",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["content_hash"] == "0" * 64
    assert session.query(AuditLog).filter_by(entity_id=payload["id"]).count() == 1
