"""Tests for the v1 review queue scheduler."""

from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import lms.audit.models  # noqa: F401  # register Base.metadata
import lms.evidence.models  # noqa: F401  # register Base.metadata
import lms.graphs.models  # noqa: F401  # register Base.metadata
import lms.learners.models  # noqa: F401  # register Base.metadata
import lms.llm.models  # noqa: F401  # register Base.metadata
import lms.prompts.models  # noqa: F401  # register Base.metadata
import lms.scheduling.models  # noqa: F401  # register Base.metadata
import lms.sources.models  # noqa: F401  # register Base.metadata
from lms.auth.models import utc_now
from lms.db.base import Base
from lms.db.session import get_session
from lms.evidence.models import Attempt, EvidenceRecord
from lms.evidence.repository import create_attempt, create_evidence_record
from lms.main import create_app
from lms.scheduling.models import ReviewQueueItem
from lms.scheduling.repository import (
    create_review_queue_item,
    list_review_queue_for_learner,
)
from lms.scheduling.service import (
    SUCCESS_INTERVALS_DAYS,
    _classify_signal,
    _success_interval_days,
    schedule_from_attempt,
    seed_new_learning_item,
)
from lms.settings import get_settings


def _make_attempt(
    session: Session,
    *,
    learner_id: str = "learner-1",
    prompt_id: str = "prompt-1",
    knowledge_node_id: str = "node-1",
    correctness: bool | None = True,
    normalized_score: float | None = None,
    confidence_rating: int | None = 4,
    support_level: str = "none",
    response_time_seconds: int | None = 30,
) -> tuple[Attempt, EvidenceRecord]:
    """Create an Attempt with an EvidenceRecord matching the requested signal."""
    attempt = create_attempt(
        session,
        learner_id=learner_id,
        prompt_id=prompt_id,
        response_text="learner response",
        feedback={
            "goal": "goal",
            "observed_evidence": "obs",
            "next_action": "next",
        },
        confidence_rating=confidence_rating,
        support_level=support_level,
        evidence={
            "knowledge_node_id": knowledge_node_id,
            "evidence_kind": "observed",
            "correctness": correctness,
            "normalized_score": normalized_score,
            "response_time_seconds": response_time_seconds,
        },
    )
    evidence = attempt.evidence_records[0]
    return attempt, evidence


def test_successful_retrieval_schedules_future_review(db_session: Session) -> None:
    """A correct, confident retrieval schedules a future due-review item."""
    attempt, evidence = _make_attempt(
        db_session,
        correctness=True,
        normalized_score=0.95,
        confidence_rating=5,
        support_level="none",
    )
    fixed_now = datetime(2026, 6, 1, 12, 0, 0, tzinfo=utc_now().tzinfo)

    item = schedule_from_attempt(
        db_session,
        attempt=attempt,
        evidence_record=evidence,
        now=fixed_now,
    )
    db_session.commit()

    assert item.reason_code == "due-review"
    assert item.due_at == fixed_now + timedelta(days=SUCCESS_INTERVALS_DAYS[0])
    assert item.priority == 0.4
    assert "Re-checking" in item.reason_explanation
    assert item.source_attempt_id == attempt.id
    assert item.source_evidence_record_id == evidence.id
    assert item.decision_log["rule"] == "success-ramp-step-0"
    assert item.decision_log["signal"] == "success"
    assert item.decision_log["inputs"]["correctness"] is True


def test_failed_retrieval_creates_remediation_item(db_session: Session) -> None:
    """A failed retrieval creates an immediate remediation queue item."""
    attempt, evidence = _make_attempt(
        db_session,
        correctness=False,
        normalized_score=0.1,
        confidence_rating=2,
    )
    fixed_now = datetime(2026, 6, 1, 12, 0, 0, tzinfo=utc_now().tzinfo)

    item = schedule_from_attempt(
        db_session,
        attempt=attempt,
        evidence_record=evidence,
        now=fixed_now,
    )
    db_session.commit()

    assert item.reason_code == "remediation"
    assert item.due_at == fixed_now
    assert item.priority == 0.9
    assert "remediation" in item.reason_explanation.lower()
    assert item.decision_log["rule"] == "failure-immediate-remediation"
    assert item.decision_log["signal"] == "fail"


def test_low_confidence_success_shortens_interval(db_session: Session) -> None:
    """A correct answer with low confidence schedules a short follow-up review."""
    attempt, evidence = _make_attempt(
        db_session,
        correctness=True,
        normalized_score=0.9,
        confidence_rating=2,
    )
    fixed_now = datetime(2026, 6, 1, 12, 0, 0, tzinfo=utc_now().tzinfo)

    item = schedule_from_attempt(
        db_session,
        attempt=attempt,
        evidence_record=evidence,
        now=fixed_now,
    )

    assert item.reason_code == "due-review"
    assert item.due_at == fixed_now + timedelta(days=1)
    assert item.priority == 0.7
    assert item.decision_log["signal"] == "low-confidence-success"
    assert "confidence=2/5" in item.reason_explanation


def test_support_use_treated_as_low_confidence(db_session: Session) -> None:
    """Using a hint or reference counts as a low-confidence signal."""
    attempt, evidence = _make_attempt(
        db_session,
        correctness=True,
        normalized_score=0.92,
        confidence_rating=5,
        support_level="hint",
    )

    item = schedule_from_attempt(db_session, attempt=attempt, evidence_record=evidence)

    assert item.reason_code == "due-review"
    assert item.decision_log["signal"] == "low-confidence-success"
    assert "support=hint" in item.reason_explanation


def test_success_ramp_extends_after_prior_completions(db_session: Session) -> None:
    """Each completed prior review steps the success interval up the v1 ramp."""
    attempt, evidence = _make_attempt(
        db_session,
        correctness=True,
        normalized_score=0.95,
        confidence_rating=5,
    )
    first = schedule_from_attempt(db_session, attempt=attempt, evidence_record=evidence)
    first.status = "completed"
    db_session.flush()

    attempt_two, evidence_two = _make_attempt(
        db_session,
        learner_id=attempt.learner_id,
        knowledge_node_id=evidence.knowledge_node_id,
        prompt_id="prompt-2",
        correctness=True,
        normalized_score=0.95,
        confidence_rating=5,
    )
    fixed_now = datetime(2026, 6, 1, 12, 0, 0, tzinfo=utc_now().tzinfo)
    second = schedule_from_attempt(
        db_session,
        attempt=attempt_two,
        evidence_record=evidence_two,
        now=fixed_now,
    )
    assert second.due_at == fixed_now + timedelta(days=SUCCESS_INTERVALS_DAYS[1])
    assert second.decision_log["rule"] == "success-ramp-step-1"


def test_seed_new_learning_item_creates_pending_entry(db_session: Session) -> None:
    """The new-learning seed helper creates an immediately-due item."""
    fixed_now = datetime(2026, 6, 1, 12, 0, 0, tzinfo=utc_now().tzinfo)
    item = seed_new_learning_item(
        db_session,
        learner_id="learner-9",
        knowledge_node_id="node-9",
        now=fixed_now,
    )
    db_session.commit()

    assert item.reason_code == "new-learning"
    assert item.status == "pending"
    assert item.due_at == fixed_now
    assert item.decision_log["rule"] == "seed-new-learning"


def test_list_review_queue_orders_by_due_then_priority(db_session: Session) -> None:
    """Queue listing returns pending items sorted by due_at then priority."""
    attempt_a, evidence_a = _make_attempt(
        db_session,
        learner_id="learner-x",
        knowledge_node_id="node-a",
        prompt_id="prompt-a",
        correctness=False,
        normalized_score=0.0,
    )
    attempt_b, evidence_b = _make_attempt(
        db_session,
        learner_id="learner-x",
        knowledge_node_id="node-b",
        prompt_id="prompt-b",
        correctness=True,
        normalized_score=0.95,
        confidence_rating=5,
    )
    fixed_now = datetime(2026, 6, 1, 12, 0, 0, tzinfo=utc_now().tzinfo)
    schedule_from_attempt(db_session, attempt=attempt_a, evidence_record=evidence_a, now=fixed_now)
    schedule_from_attempt(db_session, attempt=attempt_b, evidence_record=evidence_b, now=fixed_now)
    db_session.commit()

    items = list_review_queue_for_learner(db_session, learner_id="learner-x")
    assert [item.reason_code for item in items] == ["remediation", "due-review"]


def test_reason_explanations_are_plain_language(db_session: Session) -> None:
    """Every emitted reason carries a human-readable explanation string."""
    attempt, evidence = _make_attempt(
        db_session,
        correctness=True,
        normalized_score=0.95,
        confidence_rating=5,
    )
    item = schedule_from_attempt(db_session, attempt=attempt, evidence_record=evidence)
    assert isinstance(item.reason_explanation, str)
    assert len(item.reason_explanation.split()) >= 4
    assert item.reason_explanation == item.reason_explanation.strip()


def test_decision_log_captures_inputs_and_output(db_session: Session) -> None:
    """The decision log records inputs and outputs for Inspect display."""
    attempt, evidence = _make_attempt(
        db_session,
        correctness=True,
        normalized_score=0.95,
        confidence_rating=5,
    )
    item = schedule_from_attempt(db_session, attempt=attempt, evidence_record=evidence)
    log = item.decision_log
    assert set(log.keys()) >= {"rule", "signal", "inputs", "output"}
    assert log["inputs"]["evidence_record_id"] == evidence.id
    assert log["inputs"]["attempt_id"] == attempt.id
    assert log["output"]["reason_code"] == item.reason_code


def test_queue_item_check_constraints_reject_invalid_state(db_session: Session) -> None:
    """The reason_code and status check constraints reject unknown values."""
    fixed_now = datetime(2026, 6, 1, 12, 0, 0, tzinfo=utc_now().tzinfo)
    with pytest.raises(IntegrityError):
        create_review_queue_item(
            db_session,
            learner_id="learner-z",
            knowledge_node_id="node-z",
            reason_code="not-a-real-code",
            reason_explanation="bad",
            due_at=fixed_now,
            decision_log={"rule": "test"},
        )
        db_session.flush()


def test_alembic_upgrade_head_creates_review_queue_items_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Upgrading to head should materialize the review_queue_items table."""
    db_path = tmp_path / "migration.db"
    db_url = f"sqlite:///{db_path}"

    monkeypatch.setenv("DATABASE_URL", db_url)
    get_settings.cache_clear()
    config = Config("alembic.ini")

    command.upgrade(config, "head")

    engine = create_engine(db_url, future=True)
    try:
        tables = set(inspect(engine).get_table_names())
        review_queue_columns = {
            column["name"] for column in inspect(engine).get_columns("review_queue_items")
        }
    finally:
        engine.dispose()

    assert "review_queue_items" in tables
    assert {
        "id",
        "learner_id",
        "knowledge_node_id",
        "reason_code",
        "reason_explanation",
        "due_at",
        "priority",
        "status",
        "source_attempt_id",
        "source_evidence_record_id",
        "decision_log",
        "created_at",
        "updated_at",
    } <= review_queue_columns


def test_review_queue_endpoint_returns_items_with_reasons() -> None:
    """The GET /learners/{id}/review-queue endpoint returns reason codes + explanations."""
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    session = session_factory()
    try:
        attempt, evidence = _make_attempt(
            session,
            learner_id="learner-api",
            knowledge_node_id="node-api",
            correctness=False,
            normalized_score=0.0,
        )
        schedule_from_attempt(session, attempt=attempt, evidence_record=evidence)
        session.commit()
    finally:
        session.close()

    def override_session() -> Generator[Session, None, None]:
        s = session_factory()
        try:
            yield s
        finally:
            s.close()

    app = create_app(enable_local_identity_routes=False)
    app.dependency_overrides[get_session] = override_session
    client = TestClient(app)

    try:
        response = client.get("/learners/learner-api/review-queue")
        assert response.status_code == 200
        payload = response.json()
        assert len(payload) == 1
        entry = payload[0]
        assert entry["reason_code"] == "remediation"
        assert isinstance(entry["reason_explanation"], str)
        assert entry["learner_id"] == "learner-api"
        assert entry["knowledge_node_id"] == "node-api"
        assert entry["status"] == "pending"

        empty = client.get("/learners/no-such-learner/review-queue")
        assert empty.status_code == 200
        assert empty.json() == []
    finally:
        client.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_review_queue_item_table_constraints_block_bad_priority(db_session: Session) -> None:
    """Priority out of unit interval is rejected by the check constraint."""
    item = ReviewQueueItem(
        learner_id="learner-y",
        knowledge_node_id="node-y",
        reason_code="due-review",
        reason_explanation="ok",
        due_at=utc_now(),
        priority=1.5,
        decision_log={"rule": "test"},
    )
    db_session.add(item)
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_success_interval_clamps_negative_prior_successes() -> None:
    """Negative prior_successes is treated as zero."""
    assert _success_interval_days(-1) == _success_interval_days(0)


def test_success_interval_caps_at_max_ramp() -> None:
    """Prior successes beyond the ramp length returns the last interval."""
    beyond = len(SUCCESS_INTERVALS_DAYS) + 5
    assert _success_interval_days(beyond) == SUCCESS_INTERVALS_DAYS[-1]


def test_classify_signal_fail_via_normalized_score_only() -> None:
    """A low normalized score with no explicit correctness flag returns 'fail'."""
    signal = _classify_signal(
        correctness=None,
        normalized_score=0.2,
        confidence_rating=5,
        support_level="none",
    )
    assert signal == "fail"


def test_classify_signal_low_confidence_via_score_below_threshold() -> None:
    """A passing score below the success threshold triggers low-confidence-success."""
    signal = _classify_signal(
        correctness=None,
        normalized_score=0.7,
        confidence_rating=None,
        support_level="none",
    )
    assert signal == "low-confidence-success"


def test_classify_signal_fallback_low_confidence_no_score() -> None:
    """When correctness is unknown and no score, falls back to low-confidence-success."""
    signal = _classify_signal(
        correctness=None,
        normalized_score=None,
        confidence_rating=None,
        support_level="none",
    )
    assert signal == "low-confidence-success"


def test_low_confidence_decision_includes_score_in_reasons(db_session: Session) -> None:
    """Low score without explicit failure populates normalized_score reason."""
    attempt, evidence = _make_attempt(
        db_session,
        correctness=None,
        normalized_score=0.7,
        confidence_rating=None,
        support_level="none",
    )
    item = schedule_from_attempt(db_session, attempt=attempt, evidence_record=evidence)
    assert item.decision_log["signal"] == "low-confidence-success"
    assert "normalized_score=0.70" in item.reason_explanation


def test_low_confidence_decision_no_reason_details_uses_fallback(db_session: Session) -> None:
    """When signal is low-confidence but no specific reason is derivable, a fallback phrase is used."""
    attempt = create_attempt(
        db_session,
        learner_id="learner-fb",
        prompt_id="prompt-fb",
        response_text="answer",
        feedback={"goal": "g", "observed_evidence": "o", "next_action": "n"},
        confidence_rating=None,
        support_level="none",
    )
    evidence = create_evidence_record(
        db_session,
        learner_id="learner-fb",
        knowledge_node_id="node-fb",
        attempt_id=attempt.id,
        correctness=None,
        normalized_score=None,
        confidence_rating=None,
        support_level="none",
    )
    item = schedule_from_attempt(db_session, attempt=attempt, evidence_record=evidence)
    assert item.decision_log["signal"] == "low-confidence-success"
    assert "low-confidence signal" in item.reason_explanation


def test_schedule_from_attempt_rejects_mismatched_evidence(db_session: Session) -> None:
    """schedule_from_attempt raises ValueError when evidence belongs to a different attempt."""
    attempt_a, evidence_a = _make_attempt(db_session, learner_id="la", prompt_id="pa")
    attempt_b, _ = _make_attempt(
        db_session, learner_id="la", prompt_id="pb", knowledge_node_id="node-b"
    )
    with pytest.raises(ValueError, match="does not belong to attempt"):
        schedule_from_attempt(db_session, attempt=attempt_b, evidence_record=evidence_a)


def test_schedule_from_attempt_rejects_none_evidence_record(db_session: Session) -> None:
    """schedule_from_attempt raises ValueError when evidence_record is None."""
    attempt, _ = _make_attempt(db_session, learner_id="learner-none", prompt_id="prompt-none")
    with pytest.raises(ValueError, match="requires an evidence_record"):
        schedule_from_attempt(db_session, attempt=attempt, evidence_record=None)


def test_list_review_queue_returns_all_statuses_when_status_is_none(
    db_session: Session,
) -> None:
    """list_review_queue_for_learner with status=None returns items of any status."""
    attempt_a, evidence_a = _make_attempt(
        db_session,
        learner_id="learner-ns",
        knowledge_node_id="node-ns-a",
        prompt_id="prompt-ns-a",
        correctness=False,
        normalized_score=0.0,
    )
    attempt_b, evidence_b = _make_attempt(
        db_session,
        learner_id="learner-ns",
        knowledge_node_id="node-ns-b",
        prompt_id="prompt-ns-b",
        correctness=True,
        normalized_score=0.95,
        confidence_rating=5,
    )
    item_a = schedule_from_attempt(db_session, attempt=attempt_a, evidence_record=evidence_a)
    item_b = schedule_from_attempt(db_session, attempt=attempt_b, evidence_record=evidence_b)
    item_a.status = "completed"
    db_session.flush()

    all_items = list_review_queue_for_learner(db_session, learner_id="learner-ns", status=None)
    pending_only = list_review_queue_for_learner(
        db_session, learner_id="learner-ns", status="pending"
    )

    assert len(all_items) == 2
    assert {i.id for i in all_items} == {item_a.id, item_b.id}
    assert len(pending_only) == 1
    assert pending_only[0].id == item_b.id


def test_schedule_from_attempt_rejects_unlinked_evidence(db_session: Session) -> None:
    """schedule_from_attempt requires evidence to be linked to the attempt."""
    attempt, _ = _make_attempt(db_session, learner_id="learner-linked", prompt_id="prompt-linked")
    evidence = create_evidence_record(
        db_session,
        learner_id=attempt.learner_id,
        knowledge_node_id="node-unlinked",
        attempt_id=None,
        correctness=True,
        normalized_score=0.95,
        confidence_rating=5,
        support_level="none",
    )

    with pytest.raises(ValueError, match="does not belong to attempt"):
        schedule_from_attempt(db_session, attempt=attempt, evidence_record=evidence)
