"""Tests for learner attempt submission."""

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
from lms.main import create_app


@pytest.fixture
def api_client() -> Generator[TestClient, None, None]:
    """Provide a FastAPI client backed by an in-memory SQLite database."""
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
            yield client
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def _attempt_payload() -> dict[str, object]:
    return {
        "learner_id": "learner-1",
        "prompt_id": "prompt-1",
        "response_text": "I used inverse operations to isolate x.",
        "confidence_rating": 4,
        "reference_accessed": True,
        "hint_used": False,
        "support_level": "reference",
        "elapsed_seconds": 42,
        "feedback": {
            "goal": "Solve one-step equations",
            "observed_evidence": "Explained inverse operation choice.",
            "gap": "Needs a numeric example.",
            "next_action": "Practice two one-step equations.",
        },
    }


def test_submit_attempt_with_confidence_and_reference_use(api_client: TestClient) -> None:
    """POST /attempts returns a stable id with confidence and reference tracking."""
    response = api_client.post("/attempts", json=_attempt_payload())

    assert response.status_code == 201
    body = response.json()
    assert body["id"]
    assert body["learner_id"] == "learner-1"
    assert body["prompt_id"] == "prompt-1"
    assert body["confidence_rating"] == 4
    assert body["reference_accessed"] is True
    assert body["support_level"] == "reference"


def test_structured_feedback_requires_next_action(api_client: TestClient) -> None:
    """Attempt feedback must include an actionable learner next step."""
    payload = _attempt_payload()
    payload["feedback"] = {
        "goal": "Solve one-step equations",
        "observed_evidence": "Explained inverse operation choice.",
        "gap": "Needs a numeric example.",
    }

    response = api_client.post("/attempts", json=payload)

    assert response.status_code == 422


def test_attempt_confidence_validation(api_client: TestClient) -> None:
    """Confidence is bounded to the v1 five-point learner rating scale."""
    payload = _attempt_payload()
    payload["confidence_rating"] = 6

    response = api_client.post("/attempts", json=payload)

    assert response.status_code == 422


def test_get_attempt_returns_recorded_feedback(api_client: TestClient) -> None:
    """GET /attempts/{id} returns the stored structured feedback."""
    created = api_client.post("/attempts", json=_attempt_payload()).json()

    response = api_client.get(f"/attempts/{created['id']}")

    assert response.status_code == 200
    body = response.json()
    assert body["feedback"]["next_action"] == "Practice two one-step equations."
