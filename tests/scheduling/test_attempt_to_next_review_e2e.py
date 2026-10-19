"""HTTP-level loop gate: attempt -> evidence -> queue -> completion -> ramp.

Audit finding LMS-R2 (2026-08-01): scored attempts submitted through
``POST /attempts`` (and the UI forms) persisted evidence but never invoked the
scheduler, and the UI offered no scoring or completion step — so the learning
loop silently stopped after the first attempt while every unit test stayed
green. This suite drives the REAL ``create_app()`` over HTTP with no manual
queue-status writes, pinning the wiring between the tested units.
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, timedelta
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import lms.audit.models  # noqa: F401
import lms.cases.models  # noqa: F401
import lms.evidence.models  # noqa: F401
import lms.feedback.models  # noqa: F401
import lms.graphs.models  # noqa: F401
import lms.learners.models  # noqa: F401
import lms.llm.models  # noqa: F401
import lms.llm.proposals  # noqa: F401
import lms.maintenance.models  # noqa: F401
import lms.prompts.models  # noqa: F401
import lms.scheduling.models  # noqa: F401
import lms.sources.models  # noqa: F401
from lms.auth.repository import get_or_create_local_dev_user
from lms.db.base import Base
from lms.db.session import get_session
from lms.graphs.repository import create_knowledge_node
from lms.learners.repository import create_learner_for_user, create_learning_goal
from lms.main import create_app
from lms.prompts.repository import create_prompt, publish_prompt
from lms.scheduling.models import ReviewQueueItem, ReviewSchedule
from lms.sources.repository import create_source_reference

ACTOR = "system:e2e-loop-test"


@pytest.fixture
def loop_client() -> Generator[tuple[TestClient, sessionmaker[Session]], None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
    )

    def override_get_session() -> Generator[Session, None, None]:
        s = session_factory()
        try:
            yield s
        finally:
            s.close()

    app = create_app(enable_local_identity_routes=True)
    app.dependency_overrides[get_session] = override_get_session
    client = TestClient(app, follow_redirects=False)
    try:
        yield client, session_factory
    finally:
        client.close()
        app.dependency_overrides.clear()


def _seed_learner_node_prompt(session_factory: sessionmaker[Session]) -> tuple[str, str, str]:
    """Create a learner (for the local-dev user), a published node, and prompt."""
    with session_factory() as session:
        user = get_or_create_local_dev_user(session)
        learner = create_learner_for_user(session, user_id=user.id, display_name="Loop Learner")
        ref = create_source_reference(
            session,
            source_type="internal-note",
            stable_locator="docs/e2e/loop.md",
            content="Loop test source content.",
            actor_id=ACTOR,
            source_visibility="local-only",
        )
        node = create_knowledge_node(
            session,
            title="Loop test node",
            knowledge_type="conceptual",
            scope="personal",
            status="published",
            actor_id=ACTOR,
            description="Node for the e2e loop gate.",
            source_reference_id=ref.id,
        )
        goal = create_learning_goal(
            session,
            learner_id=learner.id,
            title="Loop gate goal",
            knowledge_type="conceptual",
            target_node_ids=[node.id],
            ownership_scope="personal",
        )
        prompt = create_prompt(
            session,
            target_node_id=node.id,
            learning_goal_id=goal.id,
            knowledge_type="conceptual",
            intended_cognitive_action="recall",
            demand_level="medium",
            expected_answer_form="short-text",
            body="Recall the loop test concept.",
            source_reference_ids=[ref.id],
            authoring_method="human-authored",
            authoring_actor=ACTOR,
        )
        publish_prompt(session, prompt, reviewing_actor=ACTOR)
        session.commit()
        return learner.id, node.id, prompt.id


def _attempt_payload(
    learner_id: str, node_id: str, prompt_id: str, *, response_text: str
) -> dict[str, object]:
    return {
        "learner_id": learner_id,
        "prompt_id": prompt_id,
        "response_text": response_text,
        "confidence_rating": 4,
        "feedback": {
            "goal": "Loop gate",
            "observed_evidence": response_text,
            "next_action": "Continue.",
        },
        "evidence": {
            "knowledge_node_id": node_id,
            "correctness": True,
            "raw_score": 1.0,
            "normalized_score": 1.0,
            "max_score": 1.0,
            "scorer_type": "auto",
            "scoring_method": "binary",
        },
    }


def _queue_items(session_factory: sessionmaker[Session], learner_id: str) -> list[ReviewQueueItem]:
    with session_factory() as session:
        return list(
            session.scalars(
                select(ReviewQueueItem)
                .where(ReviewQueueItem.learner_id == learner_id)
                .order_by(ReviewQueueItem.created_at)
            )
        )


def _interval_days(item: ReviewQueueItem) -> float:
    """Scheduled interval in days, tolerant of SQLite's naive datetimes."""
    due = item.due_at if item.due_at.tzinfo else item.due_at.replace(tzinfo=UTC)
    created = item.created_at if item.created_at.tzinfo else item.created_at.replace(tzinfo=UTC)
    return (due - created).total_seconds() / 86400


def test_attempt_to_next_review_e2e(
    loop_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    """Scored attempt schedules a review; completing it advances the ramp."""
    client, session_factory = loop_client
    learner_id, node_id, prompt_id = _seed_learner_node_prompt(session_factory)

    # 1. First scored attempt through the public API creates a queue item.
    response = client.post(
        "/attempts",
        json=_attempt_payload(learner_id, node_id, prompt_id, response_text="First answer."),
    )
    assert response.status_code == 201, response.text
    items = _queue_items(session_factory, learner_id)
    assert len(items) == 1, "a scored attempt must schedule its follow-up review"
    first = items[0]
    assert first.status == "pending"
    first_interval = _interval_days(first)
    # FSRS picks the interval from the tier's retention target rather than a
    # fixed ladder step, so assert the behavior: a real, short, forward check.
    assert 0 < first_interval < 14, f"first success should come back soon: {first_interval}"

    # 2. Complete the review from the UI surface (no manual status writes).
    completion = client.post(
        f"/app/learner/reviews/{first.id}/complete",
        data={"learner_id": learner_id},
    )
    assert completion.status_code == 303, completion.text
    items = _queue_items(session_factory, learner_id)
    assert [item.status for item in items] == ["completed"]

    # 3. The next scored attempt advances the ramp (1 -> 3 days).
    response = client.post(
        "/attempts",
        json=_attempt_payload(learner_id, node_id, prompt_id, response_text="Second answer."),
    )
    assert response.status_code == 201, response.text
    items = _queue_items(session_factory, learner_id)
    assert len(items) == 2
    second = items[-1]
    second_interval = _interval_days(second)
    assert second_interval > 0
    assert second.due_at > first.due_at, "the next review must be scheduled later than the first"


def test_ui_attempt_self_grade_schedules_review(
    loop_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    """The UI-only path closes the loop: attempt form -> self-grade -> queue item."""
    client, session_factory = loop_client
    learner_id, _node_id, prompt_id = _seed_learner_node_prompt(session_factory)

    # Submit through the UI attempt form (no evidence — unscored).
    response = client.post(
        "/app/learner/attempts",
        data={
            "learner_id": learner_id,
            "prompt_id": prompt_id,
            "response_text": "UI answer.",
            "confidence_rating": "4",
        },
    )
    assert response.status_code == 200, response.text
    assert "Grade yourself" in response.text or "How did you do?" in response.text
    assert _queue_items(session_factory, learner_id) == []

    with session_factory() as session:
        from lms.evidence.models import Attempt

        attempt_id = session.scalars(
            select(Attempt.id).where(Attempt.learner_id == learner_id)
        ).one()

    # Self-grade closes the loop.
    graded = client.post(
        "/app/learner/attempts/self-grade",
        data={"learner_id": learner_id, "attempt_id": attempt_id, "grade": "correct"},
    )
    assert graded.status_code == 200, graded.text
    assert "Self-graded" in graded.text
    items = _queue_items(session_factory, learner_id)
    assert len(items) == 1, "self-grading must schedule the next review"

    # Re-submitting the grade is idempotent — still exactly one queue item.
    again = client.post(
        "/app/learner/attempts/self-grade",
        data={"learner_id": learner_id, "attempt_id": attempt_id, "grade": "correct"},
    )
    assert again.status_code == 200
    assert len(_queue_items(session_factory, learner_id)) == 1


def test_configured_remediation_trigger_fires_on_production_path(
    loop_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    """A stored trigger fires from the real ingestion path, not just the helper.

    Audit LMS-R5: apply_remediation_triggers was only ever called by tests, so
    author-configured triggers had no runtime effect.
    """
    client, session_factory = loop_client
    learner_id, node_id, prompt_id = _seed_learner_node_prompt(session_factory)
    with session_factory() as session:
        from lms.scheduling.repository import create_remediation_trigger

        create_remediation_trigger(
            session,
            knowledge_node_id=node_id,
            trigger_type="high-confidence-error",
            trigger_rules={"min_confidence": 4},
            ownership_scope="personal",
        )
        session.commit()

    payload = _attempt_payload(
        learner_id, node_id, prompt_id, response_text="Confidently wrong answer."
    )
    payload["confidence_rating"] = 5
    evidence = payload["evidence"]
    assert isinstance(evidence, dict)
    evidence.update({"correctness": False, "raw_score": 0.0, "normalized_score": 0.0})

    response = client.post("/attempts", json=payload)
    assert response.status_code == 201, response.text

    items = _queue_items(session_factory, learner_id)
    reason_codes = sorted(item.reason_code for item in items)
    assert (
        "remediation" in reason_codes
    ), "a matching high-confidence-error trigger must create a remediation item"


def test_remediation_queue_item_can_be_cleared_after_failure(
    loop_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    """Failed attempts enqueue remediation items the learner can clear from the UI."""
    client, session_factory = loop_client
    learner_id, node_id, prompt_id = _seed_learner_node_prompt(session_factory)

    payload = _attempt_payload(learner_id, node_id, prompt_id, response_text="Wrong answer.")
    evidence = payload["evidence"]
    assert isinstance(evidence, dict)
    evidence.update({"correctness": False, "raw_score": 0.0, "normalized_score": 0.0})

    response = client.post("/attempts", json=payload)
    assert response.status_code == 201, response.text

    items = _queue_items(session_factory, learner_id)
    assert len(items) == 1
    remediation = items[0]
    assert remediation.reason_code == "remediation"
    assert remediation.status == "pending"

    completion = client.post(
        f"/app/learner/reviews/{remediation.id}/complete",
        data={"learner_id": learner_id},
    )
    assert completion.status_code == 303, completion.text

    items = _queue_items(session_factory, learner_id)
    assert len(items) == 1
    assert items[0].status == "completed"
    assert items[0].decision_log["events"][-1]["rule"] == "remediation-cleared"
    with session_factory() as session:
        schedule = session.scalar(
            select(ReviewSchedule).where(ReviewSchedule.review_queue_item_id == remediation.id)
        )
        assert schedule is not None
        assert schedule.schedule_state == "completed"


_CARD_FREEZE_FIELDS = (
    "stability",
    "difficulty",
    "review_count",
    "lapse_count",
    "due_at",
    "card_state",
)


@pytest.mark.parametrize("distance", ["near", "far", "novel"])
@pytest.mark.parametrize("existing_card", [False, True])
def test_transfer_attempt_keeps_fsrs_state_unchanged(
    loop_client: tuple[TestClient, sessionmaker[Session]],
    distance: str,
    existing_card: bool,
) -> None:
    """Near/far/novel transfer must not seed or advance an FSRS card.

    State-before/state-after: a cold learner gets no card and no due date; an
    existing card keeps stability/difficulty/review_count/lapse_count/due_at.
    The attempt receipt reports mutation and interval provenance, not only the
    adapter inclusion flag.
    """
    import copy

    from lms.evidence.models import Attempt, EvidenceRecord
    from lms.scheduling.models import ReviewCardState, ReviewSchedule

    client, session_factory = loop_client
    learner_id, node_id, prompt_id = _seed_learner_node_prompt(session_factory)
    if existing_card:
        result = client.post(
            "/attempts",
            json=_attempt_payload(learner_id, node_id, prompt_id, response_text="recall"),
        )
        assert result.status_code == 201
    with session_factory() as session:
        before = [
            copy.deepcopy({c.key: getattr(row, c.key) for c in ReviewCardState.__table__.columns})
            for row in session.scalars(select(ReviewCardState))
        ]
        schedules_before = session.scalars(select(func.count()).select_from(ReviewSchedule)).one()
        queue_before = len(_queue_items(session_factory, learner_id))
    if existing_card:
        assert len(before) == 1
    else:
        assert before == []

    payload = _attempt_payload(learner_id, node_id, prompt_id, response_text="transfer")
    evidence = payload["evidence"]
    assert isinstance(evidence, dict)
    evidence["transfer_distance"] = distance
    result = client.post("/attempts", json=payload)
    assert result.status_code == 201, result.text

    with session_factory() as session:
        after = [
            copy.deepcopy({c.key: getattr(row, c.key) for c in ReviewCardState.__table__.columns})
            for row in session.scalars(select(ReviewCardState))
        ]
        assert after == before
        if not existing_card:
            assert after == [], "transfer must not seed a new FSRS card"
        else:
            for field in _CARD_FREEZE_FIELDS:
                assert after[0][field] == before[0][field], field
        assert len(_queue_items(session_factory, learner_id)) == queue_before
        assert (
            session.scalars(select(func.count()).select_from(ReviewSchedule)).one()
            == schedules_before
        ), "transfer must not create a dated review schedule"

        attempt = session.get(Attempt, result.json()["id"])
        assert attempt is not None
        receipt = attempt.response_metadata["scheduling_outcome"]
        assert receipt["rule"] == "transfer-excluded"
        assert receipt["card_mutated"] is False
        assert receipt["interval_source"] == "none"
        assert receipt["fsrs_state"] is None
        assert receipt["fsrs_rating"]["scheduling_included"] is False
        assert receipt["fsrs_rating"]["value"] is None
        assert receipt["output"]["due_at"] is None
        assert (
            session.scalar(
                select(EvidenceRecord).where(EvidenceRecord.attempt_id == attempt.id)
            ).transfer_distance
            == distance
        )


def _clone_timing_prompt(
    factory: sessionmaker[Session],
    prompt_id: str,
    *,
    demand: str = "medium",
    scope: str = "personal",
    knowledge_type: str | None = None,
    cognitive_action: str | None = None,
    answer_form: str | None = None,
) -> tuple[str, str]:
    from lms.graphs.models import KnowledgeNode
    from lms.prompts.models import Prompt

    with factory() as session:
        original = session.get(Prompt, prompt_id)
        assert original is not None
        node = session.get(KnowledgeNode, original.target_node_id)
        assert node is not None
        goal_id = original.learning_goal_id
        if scope != node.ownership_scope:
            node = create_knowledge_node(
                session,
                title="Other scope",
                knowledge_type=node.knowledge_type,
                scope=scope,
                status="published",
                actor_id=ACTOR,
                source_reference_id=node.source_reference_id,
            )
            from lms.learners.models import LearningGoal

            original_goal = session.get(LearningGoal, original.learning_goal_id)
            assert original_goal is not None
            goal_id = create_learning_goal(
                session,
                learner_id=original_goal.learner_id,
                title="Other scoped timing population",
                knowledge_type=node.knowledge_type,
                target_node_ids=[node.id],
                ownership_scope=scope,
            ).id
        prompt = create_prompt(
            session,
            target_node_id=node.id,
            learning_goal_id=goal_id,
            knowledge_type=knowledge_type or original.knowledge_type,
            intended_cognitive_action=cognitive_action or original.intended_cognitive_action,
            demand_level=demand,
            expected_answer_form=answer_form or original.expected_answer_form,
            body="Another retrieval in the timing class.",
            source_reference_ids=[r.id for r in original.source_references],
            authoring_method="human-authored",
            authoring_actor=ACTOR,
        )
        publish_prompt(session, prompt, reviewing_actor=ACTOR)
        session.commit()
        return prompt.id, node.id


@pytest.mark.parametrize(
    "history, elapsed, expected_median, expected",
    [
        ([40, 40, 40], 40, 40, 4),
        ([40, 40, 40], 41, 40, 3),
        ([10, 10, 10], 40, 10, 3),
        ([], 1, None, 3),
        ([40, 40], 1, None, 3),
        # Unsorted, skewed populations distinguish the median from a mean,
        # first observation, or last observation, including even-sized history.
        ([100, 10, 40], 40, 40, 4),
        ([100, 10, 40], 41, 40, 3),
        ([100, 10, 41, 20], 30, 30.5, 4),
        ([100, 10, 41, 20], 31, 30.5, 3),
    ],
)
def test_real_http_prompt_class_timing_reaches_engine(
    loop_client, monkeypatch, history, elapsed, expected_median, expected
):
    from lms.scheduling import service

    client, factory = loop_client
    learner, node, prompt = _seed_learner_node_prompt(factory)
    for seconds in history:
        old_prompt, old_node = _clone_timing_prompt(factory, prompt)
        payload = _attempt_payload(learner, old_node, old_prompt, response_text="history")
        payload.update(confidence_rating=5, elapsed_seconds=seconds)
        assert client.post("/attempts", json=payload).status_code == 201
    observed = []
    real_advance = service.advance_card_state

    def capture(session, **kwargs):
        observed.append(kwargs["rating_value"])
        return real_advance(session, **kwargs)

    monkeypatch.setattr(service, "advance_card_state", capture)
    payload = _attempt_payload(learner, node, prompt, response_text="current")
    payload.update(confidence_rating=5, elapsed_seconds=elapsed)
    response = client.post("/attempts", json=payload)
    assert response.status_code == 201, response.text
    assert observed == [expected]
    item = _queue_items(factory, learner)[-1]
    timing = item.decision_log["inputs"]["prompt_class_timing"]
    assert timing["sample_count"] == len(history), "current response cannot count itself"
    assert timing["median_seconds"] == expected_median
    assert item.decision_log["fsrs_rating"]["value"] == expected
    if history:
        # A repeat of the same prompt can never regain first-attempt Easy.
        response = client.post("/attempts", json=payload)
        assert response.status_code == 201
        assert observed[-1] == 3


@pytest.mark.parametrize(
    "grade, confidence, expected",
    [("incorrect", 5, 1), ("partial", 5, 2), ("correct", 3, 3), ("correct", 5, 4)],
)
def test_ui_self_grade_delivers_all_four_ratings_to_engine(
    loop_client: tuple[TestClient, sessionmaker[Session]],
    monkeypatch: pytest.MonkeyPatch,
    grade: str,
    confidence: int,
    expected: int,
) -> None:
    """UI evidence creation must preserve the grade and timing through scheduling."""
    from lms.evidence.models import Attempt
    from lms.scheduling import service
    from lms.scheduling.card_state import advance_card_state

    client, factory = loop_client
    learner, node, prompt = _seed_learner_node_prompt(factory)
    for _ in range(3):
        old_prompt, old_node = _clone_timing_prompt(factory, prompt)
        payload = _attempt_payload(learner, old_node, old_prompt, response_text="history")
        payload.update(confidence_rating=5, elapsed_seconds=40)
        response = client.post("/attempts", json=payload)
        assert response.status_code == 201, response.text

    advance = Mock(wraps=advance_card_state)
    monkeypatch.setattr(service, "advance_card_state", advance)
    response = client.post(
        "/app/learner/attempts",
        data={
            "learner_id": learner,
            "prompt_id": prompt,
            "response_text": "Self-assessed answer.",
            "confidence_rating": str(confidence),
            "elapsed_seconds": "40",
        },
    )
    assert response.status_code == 200, response.text
    advance.assert_not_called()
    with factory() as session:
        attempt_id = session.scalars(
            select(Attempt.id).where(Attempt.learner_id == learner, Attempt.prompt_id == prompt)
        ).one()

    response = client.post(
        "/app/learner/attempts/self-grade",
        data={"learner_id": learner, "attempt_id": attempt_id, "grade": grade},
    )
    assert response.status_code == 200, response.text
    advance.assert_called_once()
    assert advance.call_args.kwargs["rating_value"] == expected
    decision = _queue_items(factory, learner)[-1].decision_log
    assert decision["fsrs_rating"]["value"] == expected
    assert decision["inputs"]["prompt_class_timing"]["sample_count"] == 3
    assert decision["inputs"]["prompt_class_timing"]["median_seconds"] == 40


@pytest.mark.parametrize("history_count, expected", [(2, 3), (3, 4)])
def test_duplicate_scoring_does_not_inflate_prompt_timing_history(
    loop_client: tuple[TestClient, sessionmaker[Session]],
    monkeypatch: pytest.MonkeyPatch,
    history_count: int,
    expected: int,
) -> None:
    """Extra scoring rows cannot satisfy the minimum distinct-attempt count."""
    from lms.evidence.repository import create_evidence_record
    from lms.scheduling import service

    client, factory = loop_client
    learner, node, prompt = _seed_learner_node_prompt(factory)
    for _ in range(history_count):
        old_prompt, old_node = _clone_timing_prompt(factory, prompt)
        payload = _attempt_payload(learner, old_node, old_prompt, response_text="history")
        payload.update(confidence_rating=5, elapsed_seconds=40)
        response = client.post("/attempts", json=payload)
        assert response.status_code == 201, response.text
        with factory() as session:
            create_evidence_record(
                session,
                learner_id=learner,
                knowledge_node_id=old_node,
                attempt_id=response.json()["id"],
                prompt_id=old_prompt,
                correctness=True,
                normalized_score=1.0,
                scoring_method="binary",
                confidence_rating=5,
                response_time_seconds=40,
            )
            session.commit()

    observed = []
    real_advance = service.advance_card_state

    def capture(session, **kwargs):
        observed.append(kwargs["rating_value"])
        return real_advance(session, **kwargs)

    monkeypatch.setattr(service, "advance_card_state", capture)
    payload = _attempt_payload(learner, node, prompt, response_text="current")
    payload.update(confidence_rating=5, elapsed_seconds=40)
    response = client.post("/attempts", json=payload)
    assert response.status_code == 201, response.text
    assert observed == [expected]
    timing = _queue_items(factory, learner)[-1].decision_log["inputs"]["prompt_class_timing"]
    assert timing["sample_count"] == history_count
    assert timing["median_seconds"] == (40 if history_count >= 3 else None)


@pytest.mark.parametrize(
    "excluded",
    [
        "learner",
        "scope",
        "class",
        "knowledge-type",
        "cognitive-action",
        "answer-form",
        "hint",
        "reference",
        "support",
        "low-confidence",
        "transfer",
        "zero-time",
        "unscored",
        "future",
    ],
)
def test_prompt_timing_history_does_not_cross_boundaries(loop_client, excluded):
    from lms.evidence.models import Attempt, EvidenceRecord

    client, factory = loop_client
    learner, node, prompt = _seed_learner_node_prompt(factory)
    for _ in range(3):
        old_prompt, old_node = _clone_timing_prompt(
            factory,
            prompt,
            demand="high" if excluded == "class" else "medium",
            scope="institutional" if excluded == "scope" else "personal",
            knowledge_type="procedural" if excluded == "knowledge-type" else None,
            cognitive_action="explain" if excluded == "cognitive-action" else None,
            answer_form="long-text" if excluded == "answer-form" else None,
        )
        payload = _attempt_payload(learner, old_node, old_prompt, response_text="excluded history")
        payload.update(confidence_rating=5, elapsed_seconds=100)
        if excluded == "hint":
            payload["hint_used"] = True
        if excluded == "reference":
            payload["reference_accessed"] = True
        if excluded == "support":
            payload["support_level"] = "coach"
        if excluded == "zero-time":
            payload["elapsed_seconds"] = 0
        if excluded == "low-confidence":
            payload["confidence_rating"] = 2
        if excluded == "transfer":
            payload["evidence"]["transfer_distance"] = "near"
        response = client.post("/attempts", json=payload)
        assert response.status_code == 201, response.text
        with factory() as session:
            evidence = session.scalar(
                select(EvidenceRecord).where(EvidenceRecord.attempt_id == response.json()["id"])
            )
            if excluded == "learner":
                evidence.learner_id = "other-learner"
            if excluded == "unscored":
                evidence.correctness = None
                evidence.normalized_score = None
                evidence.raw_score = None
            if excluded == "future":
                attempt = session.get(Attempt, response.json()["id"])
                assert attempt is not None
                # Imported attempts may be dated after the response being scheduled.
                # They cannot establish that response's timing threshold.
                attempt.created_at += timedelta(days=1)
            session.commit()
    payload = _attempt_payload(learner, node, prompt, response_text="current")
    payload.update(confidence_rating=5, elapsed_seconds=1)
    assert client.post("/attempts", json=payload).status_code == 201
    item = _queue_items(factory, learner)[-1]
    assert item.decision_log["inputs"]["prompt_class_timing"]["sample_count"] == 0
    assert item.decision_log["fsrs_rating"]["value"] == 3


@pytest.mark.parametrize("change", [{"hint_used": True}, {"confidence_rating": 2}])
def test_easy_timing_never_overrides_support_or_low_confidence(loop_client, monkeypatch, change):
    from lms.scheduling import service

    client, factory = loop_client
    learner, node, prompt = _seed_learner_node_prompt(factory)
    for _ in range(3):
        old_prompt, old_node = _clone_timing_prompt(factory, prompt)
        p = _attempt_payload(learner, old_node, old_prompt, response_text="history")
        p.update(confidence_rating=5, elapsed_seconds=100)
        assert client.post("/attempts", json=p).status_code == 201
    values = []
    real = service.advance_card_state

    def capture(session, **kwargs):
        values.append(kwargs["rating_value"])
        return real(session, **kwargs)

    monkeypatch.setattr(service, "advance_card_state", capture)
    p = _attempt_payload(learner, node, prompt, response_text="supported")
    p.update(confidence_rating=5, elapsed_seconds=1)
    p.update(change)
    assert client.post("/attempts", json=p).status_code == 201
    assert values == [2]
