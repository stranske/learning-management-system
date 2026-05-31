"""Runtime scheduler wiring tests for rubric-scored attempts."""

from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import lms.feedback.scoring as scoring_module
from lms.auth.dependencies import get_current_user
from lms.auth.models import User
from lms.db.base import Base
from lms.db.session import get_session
from lms.evidence.repository import create_attempt
from lms.feedback.repository import create_rubric
from lms.feedback.scoring import score_attempt_with_rubric
from lms.graphs.repository import create_knowledge_node
from lms.learners.models import Learner
from lms.main import create_app
from lms.scheduling.models import ReviewQueueItem, ReviewSchedule
from lms.scheduling.repository import complete_review_queue_item, create_review_queue_item
from lms.scheduling.service import SUCCESS_INTERVALS_DAYS


def test_rubric_scoring_runtime_advances_success_ramp(db_session: Session) -> None:
    """Production scoring plus completion advances 1 -> 3 -> 7 day reviews."""
    rubric_id, criterion_id, node_id = _rubric(db_session)
    due_gaps: list[int] = []
    rules: list[str] = []

    for index in range(3):
        attempt = create_attempt(
            db_session,
            learner_id="learner-runtime",
            prompt_id=f"prompt-runtime-{index}",
            response_text="Correct and well-supported answer.",
            feedback={
                "goal": "Use spaced repetition.",
                "observed_evidence": "Learner answered successfully.",
                "next_action": "Schedule the next review.",
            },
            confidence_rating=5,
        )
        score = score_attempt_with_rubric(
            db_session,
            rubric_id=rubric_id,
            attempt_id=attempt.id,
            scorer_type="human",
            criterion_scores=[
                {
                    "criterion_id": criterion_id,
                    "points": 5,
                    "rationale": "Complete response.",
                }
            ],
        )
        item = db_session.scalar(
            select(ReviewQueueItem).where(
                ReviewQueueItem.source_evidence_record_id == score.evidence_record_id
            )
        )

        assert item is not None
        assert item.knowledge_node_id == node_id
        due_gaps.append(round((item.due_at - item.created_at).total_seconds() / 86400))
        rules.append(item.decision_log["rule"])
        if index < 2:
            complete_review_queue_item(
                db_session,
                review_queue_item_id=item.id,
                actor_id="test:runtime-wiring",
            )
            db_session.flush()

    assert due_gaps == list(SUCCESS_INTERVALS_DAYS[:3])
    assert rules == ["success-ramp-step-0", "success-ramp-step-1", "success-ramp-step-2"]


def test_rubric_scoring_keeps_score_when_scheduler_fails(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A scheduler defect must not abort the core rubric score write."""
    rubric_id, criterion_id, _node_id = _rubric(db_session)
    attempt = create_attempt(
        db_session,
        learner_id="learner-runtime",
        prompt_id="prompt-runtime-safe",
        response_text="Correct answer.",
        feedback={"goal": "Use spaced repetition."},
        confidence_rating=5,
    )

    def fail_schedule(*_args: object, **_kwargs: object) -> None:
        raise ValueError("scheduler unavailable")

    monkeypatch.setattr(scoring_module, "schedule_from_attempt", fail_schedule)

    score = score_attempt_with_rubric(
        db_session,
        rubric_id=rubric_id,
        attempt_id=attempt.id,
        scorer_type="human",
        criterion_scores=[
            {
                "criterion_id": criterion_id,
                "points": 5,
                "rationale": "Complete response.",
            }
        ],
    )

    assert score.id
    assert score.evidence_record_id is not None


def test_complete_review_queue_route_is_authorized_and_idempotent(
    scheduling_api_client: tuple[TestClient, sessionmaker[Session], User],
) -> None:
    """The HTTP completion route records the real user and avoids duplicate events."""
    client, session_factory, current_user = scheduling_api_client
    item_id = _queue_item_for_user(
        session_factory,
        current_user,
        learner_id="learner-owned",
        reason_code="due-review",
    )

    response = client.post(f"/review-queue/{item_id}/complete")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "completed"

    repeat = client.post(f"/review-queue/{item_id}/complete")
    assert repeat.status_code == 200, repeat.text

    with session_factory() as session:
        item = session.get(ReviewQueueItem, item_id)
        assert item is not None
        assert item.status == "completed"
        assert item.decision_log["events"] == [
            {
                "rule": "review-queue-complete",
                "at": item.decision_log["events"][0]["at"],
                "actor_id": current_user.id,
                "previous_status": "pending",
            }
        ]
        schedule = session.scalar(
            select(ReviewSchedule).where(ReviewSchedule.review_queue_item_id == item_id)
        )
        assert schedule is not None
        assert schedule.schedule_state == "completed"


def test_complete_review_queue_route_rejects_non_success_reason(
    scheduling_api_client: tuple[TestClient, sessionmaker[Session], User],
) -> None:
    """Remediation items cannot be mislabeled as successful reviews."""
    client, session_factory, current_user = scheduling_api_client
    item_id = _queue_item_for_user(
        session_factory,
        current_user,
        learner_id="learner-remediation",
        reason_code="remediation",
    )

    response = client.post(f"/review-queue/{item_id}/complete")

    assert response.status_code == 409
    assert "due-review and new-learning" in response.json()["detail"]


def test_complete_review_queue_route_rejects_other_learners_item(
    scheduling_api_client: tuple[TestClient, sessionmaker[Session], User],
) -> None:
    """A caller cannot complete a queue item for a learner they do not own."""
    client, session_factory, _current_user = scheduling_api_client
    other_user = User(id="user-other", username="other", display_name="Other")
    item_id = _queue_item_for_user(
        session_factory,
        other_user,
        learner_id="learner-other",
        reason_code="due-review",
    )

    response = client.post(f"/review-queue/{item_id}/complete")

    assert response.status_code == 403


def test_complete_review_queue_route_returns_404_for_missing_item(
    scheduling_api_client: tuple[TestClient, sessionmaker[Session], User],
) -> None:
    """Missing queue items return 404 from the HTTP route."""
    client, _session_factory, _current_user = scheduling_api_client

    response = client.post("/review-queue/missing-item/complete")

    assert response.status_code == 404


def _rubric(db_session: Session) -> tuple[str, str, str]:
    node = create_knowledge_node(
        db_session,
        title="Runtime spaced repetition",
        knowledge_type="procedural",
        scope="personal",
        actor_id="user:teacher",
        status="published",
    )
    rubric = create_rubric(
        db_session,
        title="Runtime scheduler rubric",
        ownership_scope="personal",
        authoring_actor="user:teacher",
        knowledge_node_id=node.id,
        criteria=[
            {
                "criterion_order": 1,
                "description": "Successful retrieval.",
                "max_points": 5,
            }
        ],
    )
    return rubric.id, rubric.criteria[0].id, node.id


@pytest.fixture
def scheduling_api_client() -> (
    Generator[tuple[TestClient, sessionmaker[Session], User], None, None]
):
    """Provide a FastAPI client with a stable authenticated test user."""
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
    current_user = User(id="user-current", username="current", display_name="Current")
    with session_factory() as session:
        session.add(current_user)
        session.commit()

    def override_get_session() -> Generator[Session, None, None]:
        request_session = session_factory()
        try:
            yield request_session
        finally:
            request_session.close()

    def override_current_user() -> User:
        return current_user

    app = create_app()
    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_current_user] = override_current_user
    try:
        with TestClient(app) as client:
            yield client, session_factory, current_user
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def _queue_item_for_user(
    session_factory: sessionmaker[Session],
    user: User,
    *,
    learner_id: str,
    reason_code: str,
) -> str:
    with session_factory() as session:
        if session.get(User, user.id) is None:
            session.add(user)
        learner = Learner(id=learner_id, user_id=user.id, display_name=learner_id)
        session.add(learner)
        node = create_knowledge_node(
            session,
            title=f"Node for {learner_id}",
            knowledge_type="conceptual",
            scope="personal",
            actor_id=user.id,
            status="published",
        )
        item = create_review_queue_item(
            session,
            learner_id=learner.id,
            knowledge_node_id=node.id,
            reason_code=reason_code,
            reason_explanation="Complete the scheduled review.",
            due_at=node.created_at,
            decision_log={"rule": "test"},
        )
        session.add(
            ReviewSchedule(
                learner_id=learner.id,
                knowledge_node_id=node.id,
                review_queue_item_id=item.id,
                reason_code=reason_code,
                due_at=item.due_at,
                policy_version="test",
            )
        )
        session.commit()
        return item.id
