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
from datetime import UTC

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
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
from lms.scheduling.models import ReviewQueueItem
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
