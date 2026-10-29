"""Ownership-scope isolation for the Inspect overview endpoint.

Issue #20 acceptance criterion:
``tests/inspect/test_inspect_scope.py::test_inspect_does_not_mix_ownership_scopes``
must demonstrate that an Inspect overview request scoped to one learner does
not surface another learner's evidence, and that the requested
``ownership_scope`` is preserved in the response envelope.

Issue #758: same-learner mixed-scope fixtures must keep recent evidence,
mastery, and calibration within the requested ownership scope.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
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
from lms.graphs.models import KnowledgeNode
from lms.main import create_app

MIXED_LEARNER_ID = "mixed"
MIXED_PERSONAL_NODE_ID = "mixed-personal"
MIXED_INSTITUTIONAL_NODE_ID = "mixed-institutional"


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


def _seed_mixed_scope_fixture(session: Session) -> dict[str, Any]:
    """One learner with a correct personal record and an incorrect institutional record."""
    session.add_all(
        [
            KnowledgeNode(
                id=MIXED_PERSONAL_NODE_ID,
                title="Personal",
                knowledge_type="factual",
                ownership_scope="personal",
            ),
            KnowledgeNode(
                id=MIXED_INSTITUTIONAL_NODE_ID,
                title="Institutional",
                knowledge_type="factual",
                ownership_scope="institutional",
            ),
        ]
    )
    session.flush()
    create_evidence_record(
        session,
        learner_id=MIXED_LEARNER_ID,
        knowledge_node_id=MIXED_PERSONAL_NODE_ID,
        confidence_rating=5,
        correctness=True,
        timestamp=datetime(2026, 10, 17, tzinfo=UTC),
    )
    create_evidence_record(
        session,
        learner_id=MIXED_LEARNER_ID,
        knowledge_node_id=MIXED_INSTITUTIONAL_NODE_ID,
        confidence_rating=5,
        correctness=False,
        timestamp=datetime(2026, 10, 18, tzinfo=UTC),
    )
    session.commit()
    return {
        "learner_id": MIXED_LEARNER_ID,
        "personal_node_id": MIXED_PERSONAL_NODE_ID,
        "institutional_node_id": MIXED_INSTITUTIONAL_NODE_ID,
    }


def test_inspect_does_not_mix_ownership_scopes() -> None:
    with _client() as (client, session):
        session.add_all(
            [
                KnowledgeNode(
                    id="node-personal",
                    title="Personal",
                    knowledge_type="factual",
                    ownership_scope="personal",
                ),
                KnowledgeNode(
                    id="node-institutional",
                    title="Institutional",
                    knowledge_type="factual",
                    ownership_scope="institutional",
                ),
            ]
        )
        session.flush()
        create_evidence_record(
            session,
            learner_id="learner-personal",
            knowledge_node_id="node-personal",
            prompt_id="prompt-personal",
            demand_level="low",
            knowledge_type="factual",
            normalized_score=0.7,
        )
        create_evidence_record(
            session,
            learner_id="learner-institutional",
            knowledge_node_id="node-institutional",
            prompt_id="prompt-institutional",
            demand_level="medium",
            knowledge_type="procedural",
            normalized_score=0.4,
        )
        session.commit()

        personal_response = client.get(
            "/inspect/learners/learner-personal/overview",
            params={"ownership_scope": "personal"},
        )
        institutional_response = client.get(
            "/inspect/learners/learner-institutional/overview",
            params={"ownership_scope": "institutional"},
        )

    assert personal_response.status_code == 200
    assert institutional_response.status_code == 200

    personal_body = personal_response.json()
    institutional_body = institutional_response.json()

    assert personal_body["learner_id"] == "learner-personal"
    assert personal_body["ownership_scope"] == "personal"
    personal_evidence_nodes = {
        record["knowledge_node_id"] for record in personal_body["recent_evidence"]
    }
    assert personal_evidence_nodes == {"node-personal"}
    assert "node-institutional" not in personal_evidence_nodes
    personal_mastery_learners = {
        estimate["learner_id"] for estimate in personal_body["mastery"] if "learner_id" in estimate
    }
    assert personal_mastery_learners <= {"learner-personal"}

    assert institutional_body["learner_id"] == "learner-institutional"
    assert institutional_body["ownership_scope"] == "institutional"
    institutional_evidence_nodes = {
        record["knowledge_node_id"] for record in institutional_body["recent_evidence"]
    }
    assert institutional_evidence_nodes == {"node-institutional"}
    assert "node-personal" not in institutional_evidence_nodes


def test_inspect_rejects_unknown_ownership_scope() -> None:
    with _client() as (client, _session):
        response = client.get(
            "/inspect/learners/learner-x/overview",
            params={"ownership_scope": "global"},
        )

    assert response.status_code == 422


def test_mixed_scope_fixture_personal_overview_is_scope_pure() -> None:
    """Personal request sees only the correct personal record across evidence panels."""
    with _client() as (client, session):
        fixture = _seed_mixed_scope_fixture(session)
        response = client.get(
            f"/inspect/learners/{fixture['learner_id']}/overview",
            params={"ownership_scope": "personal"},
        )

    assert response.status_code == 200
    result = response.json()
    assert result["ownership_scope"] == "personal"
    assert {r["knowledge_node_id"] for r in result["recent_evidence"]} == {
        fixture["personal_node_id"]
    }
    assert {r["knowledge_node_id"] for r in result["mastery"]} == {fixture["personal_node_id"]}
    assert result["calibration"]["sample_size"] == 1
    assert result["calibration"]["buckets"][0]["observed_accuracy"] == 1.0
    assert fixture["institutional_node_id"] not in {
        r["knowledge_node_id"] for r in result["recent_evidence"]
    }
    assert fixture["institutional_node_id"] not in {
        r["knowledge_node_id"] for r in result["mastery"]
    }


@pytest.mark.parametrize("scope", ["personal", "institutional"])
def test_same_learner_scope_filters_every_evidence_panel_before_limit(scope):
    with _client() as (client, session):
        fixture = _seed_mixed_scope_fixture(session)
        # Add 30 newer institutional rows so other-scope volume exceeds the
        # recent-evidence limit (25) without crowding out the older personal row.
        for index in range(30):
            create_evidence_record(
                session,
                learner_id=fixture["learner_id"],
                knowledge_node_id=fixture["institutional_node_id"],
                confidence_rating=5,
                correctness=False,
                timestamp=datetime(2026, 10, 18, tzinfo=UTC) + timedelta(minutes=index + 1),
            )
        session.commit()
        response = client.get(
            f"/inspect/learners/{fixture['learner_id']}/overview",
            params={"ownership_scope": scope},
        )
        assert response.status_code == 200
        result = response.json()
        expected_node = f"mixed-{scope}"
        assert result["ownership_scope"] == scope
        assert {r["knowledge_node_id"] for r in result["recent_evidence"]} == {expected_node}
        assert len(result["recent_evidence"]) == (1 if scope == "personal" else 25)
        assert {r["knowledge_node_id"] for r in result["mastery"]} == {expected_node}
        assert result["calibration"]["sample_size"] == (1 if scope == "personal" else 31)
        assert result["calibration"]["buckets"][0]["observed_accuracy"] == (
            1.0 if scope == "personal" else 0.0
        )
