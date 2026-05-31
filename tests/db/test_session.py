"""Request-scoped session transaction tests."""

from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import lms.db.session as session_module
from lms.auth.models import User
from lms.db.base import Base
from lms.main import create_app


@pytest.fixture
def app_client(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[tuple[TestClient, sessionmaker[Session], list[int]], None, None]:
    """Provide an app wired to an in-memory database and commit counter."""
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
    commit_events: list[int] = []

    def count_commit(session: Session) -> None:
        if session.get_bind() is engine:
            commit_events.append(1)

    event.listen(Session, "after_commit", count_commit)
    monkeypatch.setattr(session_module, "get_engine", lambda: engine)
    app = create_app(enable_local_identity_routes=True)

    try:
        with TestClient(app) as client:
            yield client, session_factory, commit_events
    finally:
        event.remove(Session, "after_commit", count_commit)
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_get_request_does_not_commit(
    app_client: tuple[TestClient, sessionmaker[Session], list[int]],
) -> None:
    client, _session_factory, commit_events = app_client

    response = client.get("/audit/events")

    assert response.status_code == 200
    assert commit_events == []


def test_write_route_explicit_commit_persists(
    app_client: tuple[TestClient, sessionmaker[Session], list[int]],
) -> None:
    client, session_factory, commit_events = app_client

    response = client.post(
        "/auth/users",
        json={
            "username": "reader-writer",
            "display_name": "Reader Writer",
            "email": "reader.writer@example.com",
        },
    )

    assert response.status_code == 201
    assert len(commit_events) == 1
    with session_factory() as session:
        user = session.scalar(select(User).where(User.username == "reader-writer"))
    assert user is not None
