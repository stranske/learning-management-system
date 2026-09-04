"""Regression coverage for deployed learner-resource ownership boundaries."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import suppress

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from lms.auth.login import require_authenticated_user
from lms.auth.models import User
from lms.db.base import Base
from lms.db.session import get_session
from lms.evidence.models import Attempt
from lms.feedback.models import FeedbackRecord
from lms.learners.models import Learner
from lms.main import create_app
from lms.settings import Settings, get_settings


def _deployed_client() -> Generator[tuple[TestClient, Session], None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = session_factory()
    owner = User(username="owner", display_name="Owner", is_local=False)
    other_user = User(username="other", display_name="Other", is_local=False)
    session.add_all([owner, other_user])
    session.flush()
    owner_learner = Learner(user_id=owner.id, display_name="Owner learner")
    other_learner = Learner(user_id=other_user.id, display_name="Other learner")
    session.add_all([owner_learner, other_learner])
    session.flush()
    foreign_attempt = Attempt(
        learner_id=other_learner.id,
        prompt_id="foreign-prompt",
        response_text="private response text",
        feedback={
            "goal": "Foreign private goal",
            "observed_evidence": "Foreign private evidence",
            "next_action": "Keep private",
        },
    )
    owner_feedback = FeedbackRecord(
        learner_id=owner_learner.id,
        feedback_level="coaching",
        goal="Owner goal",
        observed_evidence="Owner evidence",
        source_feedback={},
    )
    foreign_feedback = FeedbackRecord(
        learner_id=other_learner.id,
        feedback_level="coaching",
        goal="Foreign goal",
        observed_evidence="Foreign evidence",
        source_feedback={},
    )
    session.add_all([foreign_attempt, owner_feedback, foreign_feedback])
    session.commit()

    def override_session() -> Generator[Session, None, None]:
        yield session

    app = create_app()
    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_settings] = lambda: Settings(auth_required=True)
    app.dependency_overrides[require_authenticated_user] = lambda: owner
    try:
        with TestClient(app) as client:
            client.owner_learner_id = owner_learner.id  # type: ignore[attr-defined]
            client.other_learner_id = other_learner.id  # type: ignore[attr-defined]
            client.foreign_attempt_id = foreign_attempt.id  # type: ignore[attr-defined]
            yield client, session
    finally:
        app.dependency_overrides.clear()
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_authenticated_user_cannot_fetch_another_learners_attempt() -> None:
    """Foreign object IDs must not reveal a response body in deployed mode."""
    fixture = _deployed_client()
    client, _ = next(fixture)
    try:
        response = client.get(f"/attempts/{client.foreign_attempt_id}")  # type: ignore[attr-defined]
        assert response.status_code in {403, 404}
        assert "private response text" not in response.text
    finally:
        with suppress(StopIteration):
            next(fixture)


def test_authenticated_user_cannot_list_another_learners_feedback() -> None:
    """A foreign learner filter cannot disclose another learner's feedback."""
    fixture = _deployed_client()
    client, _ = next(fixture)
    try:
        foreign = client.get(f"/feedback?learner_id={client.other_learner_id}")  # type: ignore[attr-defined]
        assert foreign.status_code in {403, 404}
        own = client.get(f"/feedback?learner_id={client.owner_learner_id}")  # type: ignore[attr-defined]
        assert own.status_code == 200
        assert [record["goal"] for record in own.json()] == ["Owner goal"]
    finally:
        with suppress(StopIteration):
            next(fixture)
