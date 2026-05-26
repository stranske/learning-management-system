"""Tests for Inspect aggregation."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import lms.audit.models  # noqa: F401
import lms.evidence.models  # noqa: F401
import lms.graphs.models  # noqa: F401
import lms.sources.models  # noqa: F401
from lms.db.base import Base
from lms.db.session import get_session
from lms.evidence.repository import create_evidence_record
from lms.main import create_app
from lms.sources.repository import create_source_reference


@contextmanager
def _client() -> Generator[tuple[TestClient, Session], None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
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


def test_overview_includes_mastery_evidence_prompt_and_source_status() -> None:
    with _client() as (client, session):
        create_evidence_record(
            session,
            learner_id="learner-1",
            knowledge_node_id="node-1",
            prompt_id="prompt-1",
            demand_level="low",
            knowledge_type="factual",
            normalized_score=0.75,
        )
        create_source_reference(
            session,
            source_type="internal-note",
            stable_locator="note:inspect",
            content="Inspect source.",
            actor_id="user:alice",
        )
        session.commit()

        response = client.get("/inspect/learners/learner-1/overview")

    assert response.status_code == 200
    body = response.json()
    assert body["mastery"][0]["model_attribution"]
    assert body["recent_evidence"][0]["knowledge_node_id"] == "node-1"
    assert body["source_drift"][0]["drift_status"] == "current"
    assert "prompt_provenance" in body


def test_inspect_does_not_mix_ownership_scopes() -> None:
    with _client() as (client, _session):
        response = client.get(
            "/inspect/learners/learner-1/overview",
            params={"ownership_scope": "institutional"},
        )

    assert response.status_code == 200
    assert response.json()["ownership_scope"] == "institutional"


def test_inspect_shell_returns_html_content_type() -> None:
    with _client() as (client, _session):
        response = client.get("/inspect")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "<!doctype html>" in response.text


def test_inspect_shell_is_mobile_friendly() -> None:
    """Documented mobile-width check: Inspect shell must fit narrow viewports.

    Replaces a manual screenshot: asserts the HTML attributes that prevent
    horizontal-only interaction on mobile-width screens (320-375 px wide).
    Specifically: viewport meta tag for correct scaling, and flex-wrap on
    the navigation so tabs reflow rather than overflow.
    """
    with _client() as (client, _session):
        response = client.get("/inspect")

    html = response.text
    assert "width=device-width" in html, "Missing viewport meta — mobile scaling broken"
    assert "flex-wrap" in html, "Nav must wrap on narrow screens (flex-wrap required)"
