"""Tests for metacognitive calibration analytics (issue #203)."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import lms.audit.models  # noqa: F401
import lms.evidence.models  # noqa: F401
import lms.graphs.models  # noqa: F401
import lms.sources.models  # noqa: F401
from lms.analytics.calibration import calibration_for_learner
from lms.api.inspect import learner_calibration_route
from lms.db.base import Base
from lms.evidence.repository import create_evidence_record


def _record(session: Session, learner_id: str, *, confidence: int, correct: bool) -> None:
    create_evidence_record(
        session,
        learner_id=learner_id,
        knowledge_node_id="node-1",
        confidence_rating=confidence,
        correctness=correct,
        response_time_seconds=30,
    )


def test_overconfident_learner_flagged(db_session: Session) -> None:
    """High confidence (5) paired with low accuracy (~0.2) is flagged."""
    # 5 high-confidence attempts, only 1 correct -> accuracy 0.2.
    for index in range(5):
        _record(db_session, "learner-over", confidence=5, correct=index == 0)
    db_session.commit()

    report = calibration_for_learner(db_session, "learner-over")

    assert report.overconfident is True
    high_bucket = next(b for b in report.buckets if b.confidence_rating == 5)
    assert high_bucket.count == 5
    assert high_bucket.observed_accuracy == 0.2
    assert high_bucket.overconfident is True
    assert high_bucket.median_response_time_seconds == 30.0


def test_well_calibrated_learner_not_flagged(db_session: Session) -> None:
    """High confidence matched by high accuracy is not flagged."""
    for index in range(5):
        # 4 of 5 correct at confidence 5 -> accuracy 0.8.
        _record(db_session, "learner-ok", confidence=5, correct=index != 0)
    # Low confidence + low accuracy is honest, not overconfident.
    for _ in range(3):
        _record(db_session, "learner-ok", confidence=1, correct=False)
    db_session.commit()

    report = calibration_for_learner(db_session, "learner-ok")

    assert report.overconfident is False
    assert all(not bucket.overconfident for bucket in report.buckets)


def test_normalized_score_used_when_correctness_missing(db_session: Session) -> None:
    """Records without a boolean correctness fall back to normalized_score."""
    for _ in range(3):
        create_evidence_record(
            db_session,
            learner_id="learner-score",
            knowledge_node_id="node-1",
            confidence_rating=5,
            correctness=None,
            normalized_score=0.1,
        )
    db_session.commit()

    report = calibration_for_learner(db_session, "learner-score")

    bucket = next(b for b in report.buckets if b.confidence_rating == 5)
    assert bucket.observed_accuracy == pytest.approx(0.1)
    assert report.overconfident is True


def test_unrated_or_unscored_records_ignored(db_session: Session) -> None:
    """Records lacking confidence or any accuracy signal do not count."""
    create_evidence_record(
        db_session,
        learner_id="learner-sparse",
        knowledge_node_id="node-1",
        confidence_rating=None,
        correctness=True,
    )
    create_evidence_record(
        db_session,
        learner_id="learner-sparse",
        knowledge_node_id="node-1",
        confidence_rating=4,
        correctness=None,
        normalized_score=None,
    )
    db_session.commit()

    report = calibration_for_learner(db_session, "learner-sparse")

    assert report.sample_size == 0
    assert report.buckets == []
    assert report.overconfident is False


@contextmanager
def _session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = session_factory()

    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_knowledge_node_filter_isolates_records(db_session: Session) -> None:
    """Passing knowledge_node_id excludes records from other nodes."""
    # Overconfident on node-A.
    for index in range(5):
        create_evidence_record(
            db_session,
            learner_id="learner-filter",
            knowledge_node_id="node-A",
            confidence_rating=5,
            correctness=index == 0,
        )
    # Well-calibrated on node-B (would dilute if not filtered).
    for _ in range(5):
        create_evidence_record(
            db_session,
            learner_id="learner-filter",
            knowledge_node_id="node-B",
            confidence_rating=5,
            correctness=True,
        )
    db_session.commit()

    report = calibration_for_learner(db_session, "learner-filter", knowledge_node_id="node-A")

    assert report.knowledge_node_id == "node-A"
    assert report.sample_size == 5
    assert report.overconfident is True


def test_calibration_endpoint_surfaces_overconfidence() -> None:
    """The Inspect calibration endpoint returns the flag over a real request."""
    with _session() as session:
        for index in range(5):
            _record(session, "learner-api", confidence=5, correct=index == 0)
        session.commit()
        payload = learner_calibration_route("learner-api", session)

    assert payload["learner_id"] == "learner-api"
    assert payload["overconfident"] is True
    assert any(bucket["confidence_rating"] == 5 for bucket in payload["buckets"])


def test_calibration_endpoint_filters_by_knowledge_node() -> None:
    """The Inspect calibration endpoint forwards knowledge_node_id filtering."""
    with _session() as session:
        for index in range(5):
            create_evidence_record(
                session,
                learner_id="learner-api-filter",
                knowledge_node_id="node-A",
                confidence_rating=5,
                correctness=index == 0,
            )
        for _ in range(5):
            create_evidence_record(
                session,
                learner_id="learner-api-filter",
                knowledge_node_id="node-B",
                confidence_rating=5,
                correctness=True,
            )
        session.commit()
        payload = learner_calibration_route(
            "learner-api-filter",
            session,
            knowledge_node_id="node-A",
        )
    assert payload["knowledge_node_id"] == "node-A"
    assert payload["sample_size"] == 5
    assert payload["overconfident"] is True
