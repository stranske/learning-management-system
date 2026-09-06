"""Tests for metacognitive calibration analytics (issue #203)."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from math import isfinite

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.orm.attributes import set_committed_value
from sqlalchemy.pool import StaticPool

import lms.audit.models  # noqa: F401
import lms.evidence.models  # noqa: F401
import lms.graphs.models  # noqa: F401
import lms.sources.models  # noqa: F401
from lms.analytics.calibration import _record_accuracy, calibration_for_learner
from lms.db.base import Base
from lms.db.session import get_session
from lms.evidence.models import EvidenceRecord
from lms.evidence.repository import create_evidence_record
from lms.main import create_app


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


@pytest.mark.parametrize("score", [float("nan"), float("inf"), float("-inf")])
@pytest.mark.parametrize("correctness, expected", [(None, None), (True, 1.0), (False, 0.0)])
def test_nonfinite_accuracy_preserves_correctness_precedence(
    score: float, correctness: bool | None, expected: float | None
) -> None:
    record = EvidenceRecord(normalized_score=score, correctness=correctness)
    assert _record_accuracy(record) == expected


@pytest.mark.parametrize("score", [float("nan"), float("inf"), float("-inf")])
def test_calibration_ignores_nan_normalized_score(db_session: Session, score: float) -> None:
    """Corrupt loaded scores must not contribute counts, accuracy, or timing."""
    create_evidence_record(
        db_session,
        learner_id="learner-nonfinite",
        knowledge_node_id="node-1",
        confidence_rating=5,
        normalized_score=0.2,
        response_time_seconds=30,
    )
    corrupt_records = [
        create_evidence_record(
            db_session,
            learner_id="learner-nonfinite",
            knowledge_node_id="node-1",
            confidence_rating=rating,
            normalized_score=0.8,
            response_time_seconds=900,
        )
        for rating in (4, 5)
    ]
    db_session.flush()
    # SQLite turns NaN into NULL and rejects infinities. Retain corrupt loaded
    # values in the identity map so the real aggregate sees unsanitized input.
    for record in corrupt_records:
        set_committed_value(record, "normalized_score", score)

    report = calibration_for_learner(db_session, "learner-nonfinite")

    assert report.sample_size == 1
    assert len(report.buckets) == 1
    bucket = report.buckets[0]
    assert bucket.confidence_rating == 5
    assert bucket.count == 1
    assert isfinite(bucket.observed_accuracy)
    assert bucket.observed_accuracy == pytest.approx(0.2)
    assert bucket.median_response_time_seconds == 30.0
    assert bucket.overconfident is True
    assert report.overconfident is True


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


def test_calibration_endpoint_surfaces_overconfidence(db_session: Session) -> None:
    """The Inspect calibration endpoint returns the flag over a real request."""
    for index in range(5):
        _record(db_session, "learner-api", confidence=5, correct=index == 0)
    corrupt_record = create_evidence_record(
        db_session,
        learner_id="learner-api",
        knowledge_node_id="node-1",
        confidence_rating=5,
        normalized_score=0.8,
        response_time_seconds=900,
    )
    db_session.flush()
    # Use the same session in the request so SQLite cannot sanitize this NaN.
    set_committed_value(corrupt_record, "normalized_score", float("nan"))

    def override_get_session() -> Generator[Session, None, None]:
        with db_session.no_autoflush:
            yield db_session

    app = create_app()
    app.dependency_overrides[get_session] = override_get_session
    with TestClient(app) as client:
        response = client.get("/inspect/learners/learner-api/calibration")

    assert response.status_code == 200
    payload = response.json()
    assert payload["learner_id"] == "learner-api"
    assert payload["overconfident"] is True
    assert payload["sample_size"] == 5
    assert payload["buckets"] == [
        {
            "confidence_rating": 5,
            "count": 5,
            "observed_accuracy": 0.2,
            "median_response_time_seconds": 30.0,
            "overconfident": True,
        }
    ]


def test_calibration_endpoint_filters_by_knowledge_node() -> None:
    """The Inspect calibration endpoint forwards knowledge_node_id filtering."""
    with _client() as (client, session):
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

        response = client.get(
            "/inspect/learners/learner-api-filter/calibration",
            params={"knowledge_node_id": "node-A"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["knowledge_node_id"] == "node-A"
    assert payload["sample_size"] == 5
    assert payload["overconfident"] is True
