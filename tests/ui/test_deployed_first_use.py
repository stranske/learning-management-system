"""Deployed first-use gate: create-user -> login -> usable, owned learner home.

Audit finding LMS-R1 (2026-08-01): on the deployed instance the documented
first-use flow dead-ended — ``lms auth create-user`` made a User but nothing
ever created a Learner, every learner surface defaulted to the literal
``learner_id=learner-1``, and explicit ids were served without any ownership
check. These tests run the REAL ``create_app()`` with ``auth_required=True``
and ``enable_local_identity_routes=False`` (the render.yaml posture) and pin
the fixed behavior end-to-end.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
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
from lms.auth.repository import create_local_user
from lms.db.base import Base
from lms.db.session import get_session
from lms.learners.models import Learner
from lms.learners.repository import create_learner_for_user
from lms.main import create_app
from lms.settings import Settings, get_settings

OWNER_PASSWORD = "first-use-gate-passw0rd"


@pytest.fixture
def deployed_app() -> Generator[tuple[TestClient, sessionmaker[Session]], None, None]:
    """The real app factory in the deployed posture (auth on, no local identity)."""
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

    def override_get_settings() -> Settings:
        return Settings(
            auth_required=True,
            auth_secret_key="test-secret-key-for-first-use-gate",
            enable_local_identity_routes=False,
        )

    app = create_app(enable_local_identity_routes=False)
    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_settings] = override_get_settings
    client = TestClient(app, follow_redirects=False)
    try:
        yield client, session_factory
    finally:
        client.close()
        app.dependency_overrides.clear()


def _create_owner(session_factory: sessionmaker[Session]) -> str:
    """Create the owner user the way the documented CLI flow does."""
    with session_factory() as session:
        user = create_local_user(
            session,
            username="owner",
            display_name="Owner",
            email=None,
            password=OWNER_PASSWORD,
        )
        session.commit()
        return user.id


def _login(client: TestClient) -> None:
    response = client.post(
        "/login",
        data={"username": "owner", "password": OWNER_PASSWORD},
    )
    assert response.status_code in (302, 303), response.text


def test_deployed_first_use_learner_bootstrap(
    deployed_app: tuple[TestClient, sessionmaker[Session]],
) -> None:
    """create-user -> login -> /app/learner works and provisions an owned learner."""
    client, session_factory = deployed_app
    owner_user_id = _create_owner(session_factory)
    _login(client)

    response = client.get("/app/learner")

    assert response.status_code == 200, response.text
    with session_factory() as session:
        learners = list(session.query(Learner).filter(Learner.user_id == owner_user_id))
    assert len(learners) == 1, "first authenticated visit must provision one learner"
    # Identity is resolved server-side now; the legacy learner-1 literal is gone.
    assert "learner-1" not in response.text

    # A fresh learner sees onboarding guidance, not a bare empty grid.
    assert "Start here" in response.text

    # Second visit reuses the same profile — no duplicate provisioning.
    second = client.get("/app/learner")
    assert second.status_code == 200
    with session_factory() as session:
        count = session.query(Learner).filter(Learner.user_id == owner_user_id).count()
    assert count == 1


def test_deployed_explicit_learner_id_requires_ownership(
    deployed_app: tuple[TestClient, sessionmaker[Session]],
) -> None:
    """An explicit learner_id belonging to another user is refused in deployed mode."""
    client, session_factory = deployed_app
    _create_owner(session_factory)
    with session_factory() as session:
        stranger = create_local_user(
            session,
            username="stranger",
            display_name="Stranger",
            email=None,
            password="stranger-passw0rd",
        )
        session.flush()
        other_learner = create_learner_for_user(
            session,
            user_id=stranger.id,
            display_name="Stranger Learner",
        )
        session.commit()
        other_learner_id = other_learner.id

    _login(client)

    for path in (
        f"/app/learner?learner_id={other_learner_id}",
        f"/app/learner/reviews?learner_id={other_learner_id}",
        f"/app/learner/feedback?learner_id={other_learner_id}",
        f"/app/learner/attempts?learner_id={other_learner_id}",
    ):
        response = client.get(path)
        assert response.status_code == 403, f"{path} must refuse foreign learner ids"

    # The owner's own resolved home still works.
    own = client.get("/app/learner")
    assert own.status_code == 200


def test_deployed_unknown_learner_id_is_refused(
    deployed_app: tuple[TestClient, sessionmaker[Session]],
) -> None:
    """A nonexistent learner id no longer renders a silently-empty dashboard."""
    client, session_factory = deployed_app
    _create_owner(session_factory)
    _login(client)

    response = client.get("/app/learner?learner_id=learner-1")

    assert response.status_code == 403
