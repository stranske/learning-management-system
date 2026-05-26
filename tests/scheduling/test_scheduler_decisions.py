"""Tests for scheduler decision audit records."""

from __future__ import annotations

from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from lms.db.base import Base
from lms.db.session import get_session
from lms.main import create_app
from lms.scheduling.models import SchedulerDecision
from lms.scheduling.service import schedule_from_attempt
from tests.scheduling.test_review_queue import _make_attempt


def test_scheduler_decision_explains_remediation_reason(db_session: Session) -> None:
    """A failed retrieval writes a durable decision with rationale and source evidence."""
    attempt, evidence = _make_attempt(
        db_session,
        learner_id="learner-decision",
        knowledge_node_id="node-decision",
        correctness=False,
        normalized_score=0.1,
        confidence_rating=2,
        support_level="hint",
    )

    item = schedule_from_attempt(db_session, attempt=attempt, evidence_record=evidence)
    db_session.commit()

    decision = db_session.scalar(
        select(SchedulerDecision).where(SchedulerDecision.review_queue_item_id == item.id)
    )

    assert decision is not None
    assert decision.reason_code == "remediation"
    assert "remediation" in decision.decision_rationale.lower()
    assert decision.source_evidence_record_id == evidence.id
    assert decision.support_level == "hint"
    assert decision.decision_log["inputs"]["evidence_record_id"] == evidence.id


def test_scheduler_decisions_endpoint_returns_rationale_and_sources() -> None:
    """GET /scheduler-decisions exposes rationale and source evidence ids."""
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session_factory() as session:
        attempt, evidence = _make_attempt(
            session,
            learner_id="learner-api-decision",
            knowledge_node_id="node-api-decision",
            correctness=False,
            normalized_score=0.1,
        )
        schedule_from_attempt(session, attempt=attempt, evidence_record=evidence)
        session.commit()
        evidence_id = evidence.id

    def override_session() -> Generator[Session, None, None]:
        request_session = session_factory()
        try:
            yield request_session
        finally:
            request_session.close()

    app = create_app(enable_local_identity_routes=False)
    app.dependency_overrides[get_session] = override_session
    client = TestClient(app)
    try:
        response = client.get(
            "/scheduler-decisions",
            params={"learner_id": "learner-api-decision"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert len(payload) == 1
        assert payload[0]["reason_code"] == "remediation"
        assert "remediation" in payload[0]["decision_rationale"].lower()
        assert payload[0]["source_evidence_record_id"] == evidence_id
    finally:
        client.close()
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
