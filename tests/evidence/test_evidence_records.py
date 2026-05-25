"""Tests for verbose evidence records."""

from __future__ import annotations

from collections.abc import Generator

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
from lms.main import create_app


@pytest.fixture
def api_client() -> Generator[tuple[TestClient, Session], None, None]:
    """Provide a FastAPI client and direct session."""
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


def _scoring_payload() -> dict[str, object]:
    return {
        "knowledge_node_id": "node-1",
        "demand_level": "understand",
        "knowledge_type": "conceptual",
        "correctness": True,
        "retrieval_demand": "free-recall",
        "transfer_distance": "near",
        "source_match_quality": "direct",
        "scorer_id": "rubric:v1",
        "scorer_version": "2026-05-25",
        "raw_score": 4.0,
        "normalized_score": 0.8,
        "max_score": 5.0,
        "partial_credit_dimensions": {"concept": 0.5, "procedure": 0.3},
        "item_difficulty_estimate": 0.42,
        "attempt_context": {"surface": "review"},
        "validity_scope": "attempt",
        "answer_artifact_ref": "artifact://attempt/1",
    }


def test_evidence_record_roundtrip_full_schema(
    api_client: tuple[TestClient, Session],
) -> None:
    """A full observed evidence record can be persisted and queried."""
    client, session = api_client
    create_evidence_record(
        session,
        learner_id="learner-1",
        prompt_id="prompt-1",
        prompt_version_id="prompt-version-1",
        attempt_id="attempt-1",
        evidence_kind="observed",
        confidence_rating=4,
        hint_used=False,
        reference_accessed=True,
        support_level="reference",
        response_time_seconds=30,
        **_scoring_payload(),
    )
    session.commit()

    response = client.get("/evidence-records", params={"learner_id": "learner-1"})

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["knowledge_node_id"] == "node-1"
    assert body[0]["partial_credit_dimensions"] == {"concept": 0.5, "procedure": 0.3}
    assert body[0]["normalized_score"] == 0.8


def test_observed_and_inferred_evidence_are_distinct(
    api_client: tuple[TestClient, Session],
) -> None:
    """Evidence kind separates observed learner action from inferred estimates."""
    client, session = api_client
    for evidence_kind in ("observed", "inferred"):
        create_evidence_record(
            session,
            learner_id="learner-1",
            prompt_id=f"prompt-{evidence_kind}",
            evidence_kind=evidence_kind,
            **_scoring_payload(),
        )
    session.commit()

    observed = client.get("/evidence-records", params={"evidence_kind": "observed"}).json()
    inferred = client.get("/evidence-records", params={"evidence_kind": "inferred"}).json()

    assert [record["evidence_kind"] for record in observed] == ["observed"]
    assert [record["evidence_kind"] for record in inferred] == ["inferred"]


def test_attempt_submission_can_create_evidence_record(
    api_client: tuple[TestClient, Session],
) -> None:
    """POST /attempts creates observed evidence when scoring fields are supplied."""
    client, _session = api_client

    response = client.post(
        "/attempts",
        json={
            "learner_id": "learner-1",
            "prompt_id": "prompt-1",
            "response_text": "Inverse operations isolate x.",
            "confidence_rating": 4,
            "reference_accessed": True,
            "support_level": "reference",
            "elapsed_seconds": 30,
            "feedback": {
                "goal": "Solve equations",
                "observed_evidence": "Correct method.",
                "next_action": "Try a two-step equation.",
            },
            "scoring": {
                "learner_id": "learner-1",
                "prompt_id": "prompt-1",
                **_scoring_payload(),
            },
        },
    )

    assert response.status_code == 201
    evidence = client.get("/evidence-records", params={"learner_id": "learner-1"}).json()
    assert len(evidence) == 1
    assert evidence[0]["attempt_id"] == response.json()["id"]
    assert evidence[0]["reference_accessed"] is True
