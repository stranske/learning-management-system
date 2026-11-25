"""Tests for Inspect aggregation."""

from __future__ import annotations

from collections.abc import Callable, Generator
from contextlib import contextmanager

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import lms.audit.models  # noqa: F401
import lms.auth.models  # noqa: F401
import lms.evidence.models  # noqa: F401
import lms.graphs.models  # noqa: F401
import lms.learners.models  # noqa: F401
import lms.sources.models  # noqa: F401
from lms.api.inspect import _inspect_panel_summary
from lms.auth.repository import create_local_user, get_or_create_local_dev_user
from lms.db.base import Base
from lms.db.session import get_session
from lms.evidence.repository import create_evidence_record
from lms.graphs.models import KnowledgeNode
from lms.learners.models import Learner
from lms.main import create_app
from lms.settings import Settings, get_settings
from lms.sources.repository import create_source_reference


@contextmanager
def _client() -> Generator[tuple[TestClient, Session]]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = session_factory()

    def override_get_session() -> Generator[Session]:
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


@contextmanager
def _auth_required_client(
    seed: Callable[[Session], None] | None = None,
) -> Generator[TestClient]:
    """Real app factory with auth_required=True (mirrors deployed gate wiring)."""
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    if seed is not None:
        with session_factory() as seed_session:
            seed(seed_session)
            seed_session.commit()

    def override_get_session() -> Generator[Session]:
        request_session = session_factory()
        try:
            yield request_session
        finally:
            request_session.close()

    app = create_app(enable_local_identity_routes=False)
    app.dependency_overrides[get_settings] = lambda: Settings(
        auth_required=True, auth_secret_key="test-secret-not-for-prod"
    )
    app.dependency_overrides[get_session] = override_get_session
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_inspect_json_routes_require_authentication_when_auth_enabled() -> None:
    """Shell work must not bypass the same gate as the JSON overview routes."""
    with _auth_required_client() as client:
        shell = client.get(
            "/inspect",
            headers={"Accept": "application/json"},
            follow_redirects=False,
        )
        overview = client.get(
            "/inspect/learners/learner-1/overview",
            headers={"Accept": "application/json"},
            follow_redirects=False,
        )
        calibration = client.get(
            "/inspect/learners/learner-1/calibration",
            headers={"Accept": "application/json"},
            follow_redirects=False,
        )

    assert shell.status_code == 401
    assert overview.status_code == 401
    assert calibration.status_code == 401


def test_inspect_shell_redirects_unauthenticated_html_callers() -> None:
    with _auth_required_client() as client:
        response = client.get("/inspect", headers={"Accept": "text/html"}, follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"].startswith("/login")


def test_overview_includes_mastery_evidence_prompt_and_source_status() -> None:
    with _client() as (client, session):
        session.add(
            KnowledgeNode(
                id="node-1",
                title="Known node",
                knowledge_type="factual",
                ownership_scope="personal",
            )
        )
        session.flush()
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
    assert body["mastery"][0]["estimator_version"] == "exponential-retention-v1"
    assert body["mastery"][0]["confidence"] > 0.0
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


def test_inspect_shell_lists_all_owned_learners() -> None:
    """Learner picker links every owned learner, not only the selected one."""
    with _client() as (client, session):
        user = get_or_create_local_dev_user(session)
        session.add_all(
            [
                Learner(id="learner-a", user_id=user.id, display_name="Learner A"),
                Learner(id="learner-b", user_id=user.id, display_name="Learner B"),
            ]
        )
        session.commit()

        response = client.get("/inspect")

    assert response.status_code == 200
    html = response.text
    assert "/inspect?learner_id=learner-a" in html
    assert "/inspect?learner_id=learner-b" in html
    assert "Learner A" in html
    assert "Learner B" in html


def test_inspect_shell_links_to_live_overview_content() -> None:
    with _client() as (client, session):
        user = get_or_create_local_dev_user(session)
        session.add(
            Learner(
                id="learner-1",
                user_id=user.id,
                display_name="Inspect Learner",
            )
        )
        session.add(
            KnowledgeNode(
                id="node-1",
                title="Known node",
                knowledge_type="factual",
                ownership_scope="personal",
            )
        )
        session.flush()
        create_evidence_record(
            session,
            learner_id="learner-1",
            knowledge_node_id="node-1",
            prompt_id="prompt-1",
            demand_level="low",
            knowledge_type="factual",
            normalized_score=0.75,
        )
        session.commit()

        response = client.get("/inspect")

    assert response.status_code == 200
    html = response.text
    assert "/inspect?learner_id=learner-1" in html
    assert "Inspect Learner" in html
    assert "/inspect/learners/learner-1/overview" in html
    assert "Use the JSON overview endpoint for data." not in html
    for panel in ("evidence", "mastery", "prompts", "sources", "scheduler"):
        assert f"<section id='{panel}'>" in html
    assert "node-1" in html
    assert "0.75" in html


def test_inspect_shell_shows_empty_panel_summaries() -> None:
    """Shell renders read-only placeholder copy when overview panels are empty."""
    with _client() as (client, session):
        user = get_or_create_local_dev_user(session)
        session.add(
            Learner(
                id="learner-empty",
                user_id=user.id,
                display_name="Empty Panels",
            )
        )
        session.commit()

        response = client.get("/inspect", params={"learner_id": "learner-empty"})

    assert response.status_code == 200
    html = response.text
    assert "No recent evidence." in html
    assert "No mastery estimates." in html
    assert "No prompt provenance." in html
    assert "No source drift rows." in html


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


def test_inspect_shell_preserves_json_overview_routes_and_ownership_scope() -> None:
    """The HTML shell must stay aligned with the JSON overview contract."""
    with _client() as (client, session):
        user = get_or_create_local_dev_user(session)
        session.add(
            Learner(
                id="learner-1",
                user_id=user.id,
                display_name="Inspect Learner",
            )
        )
        session.add(
            KnowledgeNode(
                id="node-1",
                title="Known node",
                knowledge_type="factual",
                ownership_scope="personal",
            )
        )
        session.flush()
        create_evidence_record(
            session,
            learner_id="learner-1",
            knowledge_node_id="node-1",
            prompt_id="prompt-1",
            demand_level="low",
            knowledge_type="factual",
            normalized_score=0.75,
        )
        session.commit()

        json_response = client.get(
            "/inspect/learners/learner-1/overview",
            params={"ownership_scope": "institutional"},
        )
        shell_response = client.get(
            "/inspect",
            params={"learner_id": "learner-1", "ownership_scope": "institutional"},
        )

    assert json_response.status_code == 200
    json_body = json_response.json()
    assert json_body["ownership_scope"] == "institutional"
    assert json_body["recent_evidence"] == []

    assert shell_response.status_code == 200
    shell_html = shell_response.text
    assert "/inspect/learners/learner-1/overview?ownership_scope=institutional" in shell_html
    assert "/inspect?learner_id=learner-1&ownership_scope=institutional" in shell_html
    assert "No recent evidence." in shell_html
    assert "0.75" not in shell_html


def test_inspect_panel_summary_empty_panels() -> None:
    summaries = _inspect_panel_summary({})

    assert summaries == {
        "evidence": "No recent evidence.",
        "mastery": "No mastery estimates.",
        "prompts": "No prompt provenance.",
        "sources": "No source drift rows.",
        "scheduler": "Status unknown; 0 queue event(s), 0 decision(s)",
    }


def test_inspect_panel_summary_populated_panels() -> None:
    """Mastery summary reports the highest confidence, not the first node by id."""
    overview = {
        "recent_evidence": [
            {"knowledge_node_id": "node-late", "normalized_score": 0.9},
            {"knowledge_node_id": "node-early", "normalized_score": 0.1},
        ],
        "mastery": [
            {"knowledge_node_id": "node-a", "confidence": 0.235},
            {"knowledge_node_id": "node-z", "confidence": 0.47},
        ],
        "prompt_provenance": [
            {"id": "prompt-2", "status": "approved"},
            {"id": "prompt-1", "status": "draft"},
        ],
        "source_drift": [
            {"id": "source-2", "drift_status": "drifted"},
            {"id": "source-1", "drift_status": "current"},
            {"id": "source-0", "drift_status": "current"},
        ],
        "scheduler": {
            "status": "active",
            "events": [{"id": "event-1"}, {"id": "event-2"}],
            "decisions": [{"id": "decision-1"}],
        },
    }

    summaries = _inspect_panel_summary(overview)

    assert summaries["evidence"] == "2 record(s); latest node node-late score 0.9"
    assert summaries["mastery"] == "2 estimate(s); top confidence 0.47 on node-z"
    assert summaries["prompts"] == "2 prompt(s); latest prompt-2 status approved"
    assert summaries["sources"] == "3 source(s); latest drift drifted"
    assert summaries["scheduler"] == "Status active; 2 queue event(s), 1 decision(s)"


def _seed_owned_and_foreign_learners(session: Session) -> None:
    owner = create_local_user(
        session, username="owner", display_name="Owner", password="inspect-owner-pass-1234"
    )
    other = create_local_user(
        session, username="other", display_name="Other", password="inspect-other-pass-1234"
    )
    session.add_all(
        [
            Learner(id="owned-first", user_id=owner.id, display_name="Owned First"),
            Learner(id="owned-second", user_id=owner.id, display_name="Owned Second"),
            Learner(id="foreign-learner", user_id=other.id, display_name="Foreign Learner"),
        ]
    )
    for node_id in ("node-first", "node-second", "node-foreign"):
        session.add(
            KnowledgeNode(
                id=node_id,
                title=node_id,
                knowledge_type="factual",
                ownership_scope="personal",
            )
        )
    session.flush()
    for learner_id, node_id, score in (
        ("owned-first", "node-first", 0.25),
        ("owned-second", "node-second", 0.8),
        ("foreign-learner", "node-foreign", 0.6),
    ):
        create_evidence_record(
            session,
            learner_id=learner_id,
            knowledge_node_id=node_id,
            prompt_id=f"prompt-{node_id}",
            demand_level="low",
            knowledge_type="factual",
            normalized_score=score,
        )


def test_inspect_shell_selects_explicit_owned_learner_when_auth_required() -> None:
    with _auth_required_client(seed=_seed_owned_and_foreign_learners) as client:
        login = client.post(
            "/login",
            data={"username": "owner", "password": "inspect-owner-pass-1234"},
            follow_redirects=False,
        )
        assert login.status_code == 303

        response = client.get("/inspect", params={"learner_id": "owned-second"})
        foreign = client.get(
            "/inspect",
            params={"learner_id": "foreign-learner"},
            headers={"Accept": "application/json"},
            follow_redirects=False,
        )

    assert response.status_code == 200
    html = response.text
    assert "1 record(s); latest node node-second score 0.8" in html
    assert "node-first" not in html
    assert "/inspect/learners/owned-second/overview?ownership_scope=personal" in html
    assert (
        "<a href='/inspect?learner_id=owned-second&ownership_scope=personal'"
        ' aria-current="page">Owned Second</a>'
    ) in html
    assert (
        "<a href='/inspect?learner_id=owned-first&ownership_scope=personal'>Owned First</a>"
    ) in html
    assert html.count('aria-current="page"') == 1
    assert "foreign-learner" not in html
    assert "Foreign Learner" not in html
    assert "node-foreign" not in html

    assert foreign.status_code == 403
