"""API tests for local auth and learners."""

from __future__ import annotations

from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from lms.db.base import Base
from lms.db.session import get_session
from lms.main import create_app


def test_create_user_and_learner_endpoints() -> None:
    """The API can create local users and learner profiles in one app instance."""
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_session() -> Generator[Session, None, None]:
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app = create_app()
    app.dependency_overrides[get_session] = override_session
    client = TestClient(app)

    try:
        user_response = client.post(
            "/auth/users",
            json={
                "username": "maria",
                "display_name": "Maria Mitchell",
                "email": "maria@example.test",
            },
        )
        assert user_response.status_code == 201
        user_payload = user_response.json()

        learner_response = client.post(
            "/learners",
            json={
                "user_id": user_payload["id"],
                "display_name": "Maria",
                "timezone": "America/Chicago",
            },
        )
        assert learner_response.status_code == 201
        learner_payload = learner_response.json()
        assert learner_payload["user_id"] == user_payload["id"]
        assert learner_payload["display_name"] == "Maria"
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
