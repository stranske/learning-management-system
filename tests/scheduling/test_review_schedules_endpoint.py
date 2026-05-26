"""TestClient coverage for the /review-schedules route."""

from __future__ import annotations

from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from lms.db.base import Base
from lms.db.session import get_session
from lms.main import create_app
from lms.scheduling.service import seed_new_learning_item


def test_review_schedules_endpoint_returns_filtered_records() -> None:
    """GET /review-schedules serializes durable schedule rows and honors filters."""
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with session_factory() as session:
        seed_new_learning_item(
            session,
            learner_id="learner-A",
            knowledge_node_id="node-A",
        )
        seed_new_learning_item(
            session,
            learner_id="learner-A",
            knowledge_node_id="node-B",
        )
        seed_new_learning_item(
            session,
            learner_id="learner-B",
            knowledge_node_id="node-A",
        )
        session.commit()

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
        all_schedules = client.get("/review-schedules")
        assert all_schedules.status_code == 200
        all_payload = all_schedules.json()
        assert len(all_payload) == 3
        for row in all_payload:
            for required in (
                "id",
                "learner_id",
                "knowledge_node_id",
                "reason_code",
                "schedule_state",
                "due_at",
                "policy_version",
            ):
                assert required in row
            assert row["schedule_state"] == "scheduled"
            assert row["reason_code"] == "new-learning"

        by_learner = client.get("/review-schedules", params={"learner_id": "learner-A"})
        assert by_learner.status_code == 200
        learner_payload = by_learner.json()
        assert len(learner_payload) == 2
        assert {row["learner_id"] for row in learner_payload} == {"learner-A"}

        by_node = client.get("/review-schedules", params={"knowledge_node_id": "node-A"})
        assert by_node.status_code == 200
        node_payload = by_node.json()
        assert {row["knowledge_node_id"] for row in node_payload} == {"node-A"}
        assert len(node_payload) == 2

        scheduled_state = client.get(
            "/review-schedules",
            params={"schedule_state": "scheduled"},
        )
        assert scheduled_state.status_code == 200
        assert len(scheduled_state.json()) == 3

        no_match = client.get(
            "/review-schedules",
            params={"schedule_state": "completed"},
        )
        assert no_match.status_code == 200
        assert no_match.json() == []
    finally:
        client.close()
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
