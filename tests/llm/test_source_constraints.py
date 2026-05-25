"""Tests for source-constrained LLM policy output."""

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
import lms.learners.models  # noqa: F401
import lms.llm.models  # noqa: F401
import lms.prompts.models  # noqa: F401
import lms.sources.models  # noqa: F401
from lms.db.base import Base
from lms.db.session import get_session
from lms.llm.interaction_policy import flag_uncited_claims
from lms.main import create_app


def test_uncited_claim_is_flagged_unverified() -> None:
    flags = flag_uncited_claims(
        "Photosynthesis converts light into stored chemical energy.",
        ("source:biology-note-1",),
    )

    assert "unverified" in flags


def test_cited_claim_is_not_flagged() -> None:
    flags = flag_uncited_claims(
        "Per source:biology-note-1, photosynthesis stores chemical energy.",
        ("source:biology-note-1",),
    )

    assert flags == ()


@contextmanager
def _client() -> Generator[TestClient, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_get_session() -> Generator[Session, None, None]:
        request_session = session_factory()
        try:
            yield request_session
        finally:
            request_session.close()

    app = create_app()
    app.dependency_overrides[get_session] = override_get_session
    client = TestClient(app)
    try:
        yield client
    finally:
        client.close()
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_post_llm_sessions_sets_unverified_flag_when_sources_missing() -> None:
    with _client() as client:
        response = client.post(
            "/llm/sessions",
            json={
                "learner_id": "learner-1",
                "mode": "study-coach",
                "prompt_id": "prompt-1",
                "user_message": "Explain this concept briefly.",
                "source_constraints": ["source:required-1"],
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert "unverified" in body["flags"]
