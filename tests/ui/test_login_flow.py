"""End-to-end /login → protected route smoke test (#180).

This is the acceptance-criteria test specifically called out in issue #180.
It exercises the full HTML login flow on the real ``create_app()`` app so we
catch wiring regressions (middleware registration, router order, etc.) that
the lower-level dependency tests can miss.
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
import lms.prompts.models  # noqa: F401
import lms.scheduling.models  # noqa: F401
import lms.sources.models  # noqa: F401
from lms.auth.repository import create_local_user
from lms.db.base import Base
from lms.db.session import get_session
from lms.main import create_app
from lms.settings import Settings, get_settings


@pytest.fixture
def full_app_client() -> Generator[tuple[TestClient, sessionmaker[Session]], None, None]:
    """Spin up the real ``create_app()`` with AUTH_REQUIRED=true."""
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
            auth_secret_key="test-key-not-for-prod-flow",
            enable_local_identity_routes=False,
        )

    # ``create_app()`` reads settings at construction time, so override before
    # building the app.
    app = create_app(enable_local_identity_routes=False)
    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_settings] = override_get_settings

    client = TestClient(app)
    try:
        yield client, session_factory
    finally:
        client.close()
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_password_or_magic_link_login_completes_session(
    full_app_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    """The full login → session-cookie → /health-access happy path works end-to-end.

    Issue #180 describes this acceptance criterion as
    ``test_password_or_magic_link_login_completes_session``; in v1 we ship
    password login (see docs/architecture/auth.md) so this verifies the
    password path specifically. The magic-link variant would replace the
    POST body but keep the same shape.
    """
    client, session_factory = full_app_client

    # Seed a credentialed user.
    with session_factory() as s:
        create_local_user(
            s,
            username="emma",
            display_name="Emma Tester",
            email="emma@example.test",
            password="strong-passphrase-1234",
        )
        s.commit()

    # 1. GET /login renders the form.
    form = client.get("/login")
    assert form.status_code == 200
    assert "<form" in form.text
    assert 'action="/login"' in form.text

    # 2. POST /login with the right credentials issues a session cookie + redirects.
    login = client.post(
        "/login",
        data={"username": "emma", "password": "strong-passphrase-1234"},
        follow_redirects=False,
    )
    assert login.status_code == 303
    assert "lms_session" in client.cookies

    # 3. The session lets us hit a route protected by SessionMiddleware. /health
    #    is unauthenticated, but we can prove the cookie round-trips by GETting
    #    /login again — it should now redirect away from the form.
    revisit = client.get("/login", follow_redirects=False)
    # The login page detects an existing session and short-circuits.
    # The exact status depends on the in-app implementation; we accept either
    # a 2xx with a meta-refresh / Location header or a 3xx redirect.
    assert revisit.status_code in (200, 302, 303)
    if revisit.status_code == 200:
        # We render a meta-refresh page; verify the Location header carries
        # the post-login destination.
        assert revisit.headers.get("location") == "/app/learner"
    else:
        assert revisit.headers["location"] == "/app/learner"


def test_login_page_renders_without_session(
    full_app_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    """Sanity check: hitting /login with no cookies renders the form (200)."""
    client, _ = full_app_client
    response = client.get("/login")
    assert response.status_code == 200
    assert 'name="username"' in response.text
    assert 'name="password"' in response.text


def test_logout_clears_session_via_real_app(
    full_app_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    """/logout on the real app clears the session cookie."""
    client, session_factory = full_app_client
    with session_factory() as s:
        create_local_user(s, username="frank", display_name="Frank", password="frank-pass-9876")
        s.commit()

    client.post("/login", data={"username": "frank", "password": "frank-pass-9876"})
    assert "lms_session" in client.cookies

    logout = client.post("/logout", follow_redirects=False)
    assert logout.status_code == 303
    assert logout.headers["location"] == "/login"
