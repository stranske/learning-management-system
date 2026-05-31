"""Tests for recomputed mastery estimates."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import lms.audit.models  # noqa: F401
import lms.evidence.models  # noqa: F401
import lms.graphs.models  # noqa: F401
import lms.sources.models  # noqa: F401
from lms.db.base import Base
from lms.db.session import get_session
from lms.evidence.models import EvidenceRecord
from lms.evidence.repository import create_evidence_record
from lms.main import create_app
from lms.mastery.service import mastery_estimates_with_evidence_for_learner


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


def test_mastery_recomputes_from_evidence_history() -> None:
    """Changing evidence history changes the computed estimate."""
    with _client() as (client, session):
        create_evidence_record(
            session,
            learner_id="learner-1",
            knowledge_node_id="node-1",
            prompt_id="prompt-1",
            demand_level="medium",
            knowledge_type="procedural",
            correctness=False,
        )
        session.commit()
        first = client.get("/learners/learner-1/mastery-estimates").json()[0]

        create_evidence_record(
            session,
            learner_id="learner-1",
            knowledge_node_id="node-1",
            prompt_id="prompt-2",
            demand_level="medium",
            knowledge_type="procedural",
            normalized_score=1.0,
        )
        session.commit()
        second = client.get("/learners/learner-1/mastery-estimates").json()[0]

    assert second["current_estimate"] > first["current_estimate"]
    assert second["current_estimate"] > 0.5
    assert second["evidence_count"] == 2
    assert second["estimator_version"] == "fsrs-4.5-placeholder-v1"
    assert second["generated_at"]


def test_no_mastery_estimate_table_is_required() -> None:
    """The schema contains no materialized mastery estimate table."""
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    try:
        assert "mastery_estimates" not in inspect(engine).get_table_names()
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_mastery_estimate_orders_same_observed_at_records_deterministically(
    db_session: Session,
) -> None:
    observed_at = datetime(2026, 5, 31, 12, 0, tzinfo=UTC)
    created_at = datetime(2026, 5, 31, 12, 0, 1, tzinfo=UTC)

    first_order_rows = [
        EvidenceRecord(
            id="evidence-b",
            learner_id="learner-first",
            knowledge_node_id="node-1",
            evidence_kind="observed",
            observed_at=observed_at,
            timestamp=observed_at,
            created_at=created_at,
            normalized_score=1.0,
        ),
        EvidenceRecord(
            id="evidence-a",
            learner_id="learner-first",
            knowledge_node_id="node-1",
            evidence_kind="observed",
            observed_at=observed_at,
            timestamp=observed_at,
            created_at=created_at,
            normalized_score=0.0,
        ),
    ]
    reverse_order_rows = [
        EvidenceRecord(
            id="evidence-b-copy",
            learner_id="learner-reverse",
            knowledge_node_id="node-1",
            evidence_kind="observed",
            observed_at=observed_at,
            timestamp=observed_at,
            created_at=created_at,
            normalized_score=1.0,
        ),
        EvidenceRecord(
            id="evidence-a-copy",
            learner_id="learner-reverse",
            knowledge_node_id="node-1",
            evidence_kind="observed",
            observed_at=observed_at,
            timestamp=observed_at,
            created_at=created_at,
            normalized_score=0.0,
        ),
    ]
    db_session.add_all(first_order_rows)
    db_session.add_all(reversed(reverse_order_rows))
    db_session.commit()

    first_estimates, first_evidence = mastery_estimates_with_evidence_for_learner(
        db_session, "learner-first"
    )
    reverse_estimates, reverse_evidence = mastery_estimates_with_evidence_for_learner(
        db_session, "learner-reverse"
    )

    assert [record.normalized_score for record in first_evidence["node-1"]] == [0.0, 1.0]
    assert [record.normalized_score for record in reverse_evidence["node-1"]] == [0.0, 1.0]
    assert first_estimates[0]["current_estimate"] == reverse_estimates[0]["current_estimate"]
    assert first_estimates[0]["last_evidence_id"] == "evidence-b"
    assert reverse_estimates[0]["last_evidence_id"] == "evidence-b-copy"
