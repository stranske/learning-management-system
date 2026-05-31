"""Session/auth-gating tests (#180).

These exercise the ``require_authenticated_user`` dependency and the
SessionMiddleware wiring against a real FastAPI ``TestClient``. The fixture
flips ``AUTH_REQUIRED=true`` for the duration of the test so the production
behavior is the path under test, not the local-dev shortcut.
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.middleware.sessions import SessionMiddleware

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
from lms.auth.login import (
    SESSION_USER_ID_KEY,
    require_authenticated_user,
)
from lms.auth.login import (
    router as login_router,
)
from lms.auth.models import User
from lms.auth.repository import create_local_user
from lms.db.base import Base
from lms.db.session import get_session
from lms.settings import Settings, get_settings


@pytest.fixture
def auth_required_client() -> Generator[tuple[TestClient, sessionmaker[Session]], None, None]:
    """A FastAPI app with AUTH_REQUIRED=true and a single protected route.

    We build the smallest app that exercises ``require_authenticated_user``
    rather than instantiating the full ``create_app()`` factory, so the test
    isn't dependent on every router downstream behaving correctly.
    """
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
        return Settings(auth_required=True, auth_secret_key="test-key-not-for-prod")

    app = FastAPI()
    app.add_middleware(
        SessionMiddleware,
        secret_key="test-key-not-for-prod",
        session_cookie="lms_session",
        same_site="lax",
        https_only=False,
    )
    app.include_router(login_router)

    # Inline Annotated[...] keeps the FastAPI Depends resolution working under
    # ``from __future__ import annotations`` — a module-local type alias would
    # be invisible to FastAPI's string-based annotation introspection.
    @app.get("/protected-html")
    def protected_html(
        user: Annotated[User, Depends(require_authenticated_user)],
    ) -> dict[str, str]:
        # The Accept negotiation happens on the request, not the response;
        # the body shape doesn't matter — the test inspects status + headers.
        return {"id": user.id, "username": user.username}

    @app.get("/protected-api")
    def protected_api(
        user: Annotated[User, Depends(require_authenticated_user)],
    ) -> dict[str, str]:
        return {"id": user.id, "username": user.username}

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


def test_unauthenticated_html_request_redirects_to_login(
    auth_required_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    """A browser-style request (Accept: text/html) to a protected route 302s to /login."""
    client, _ = auth_required_client
    response = client.get(
        "/protected-html",
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    location = response.headers["location"]
    assert location.startswith("/login")
    # The original path is preserved so the user lands back there after login.
    assert "next=" in location
    assert "%2Fprotected-html" in location


def test_unauthenticated_api_request_returns_401(
    auth_required_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    """An API-style request (Accept: application/json) gets 401, not an HTML redirect."""
    client, _ = auth_required_client
    response = client.get(
        "/protected-api",
        headers={"Accept": "application/json"},
        follow_redirects=False,
    )
    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required."}


def test_authenticated_session_grants_access(
    auth_required_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    """After logging in with valid credentials, the session cookie grants access."""
    client, session_factory = auth_required_client

    # Seed a credentialed user.
    with session_factory() as s:
        create_local_user(
            s,
            username="alice",
            display_name="Alice Test",
            email="alice@example.test",
            password="hunter2-correct-horse",
        )
        s.commit()

    # Log in: form-encoded POST to /login.
    login = client.post(
        "/login",
        data={
            "username": "alice",
            "password": "hunter2-correct-horse",
            "next": "/protected-html",
        },
        follow_redirects=False,
    )
    assert login.status_code == 303
    assert login.headers["location"] == "/protected-html"

    # The session cookie is now set on the TestClient.
    assert "lms_session" in client.cookies

    # Subsequent requests are authenticated.
    response = client.get("/protected-html", headers={"Accept": "text/html"})
    assert response.status_code == 200
    body = response.json()
    assert body["username"] == "alice"


def test_login_failure_re_renders_form_with_401(
    auth_required_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = auth_required_client
    with session_factory() as s:
        create_local_user(
            s,
            username="bob",
            display_name="Bob Test",
            password="real-password",
        )
        s.commit()

    response = client.post(
        "/login",
        data={"username": "bob", "password": "wrong", "next": "/protected-html"},
        follow_redirects=False,
    )
    assert response.status_code == 401
    # The form is re-rendered as HTML — verify the input fields are present.
    assert "<form" in response.text
    assert 'name="username"' in response.text
    assert "Invalid username or password" in response.text


def test_login_rejects_oversized_password_input(
    auth_required_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    """Oversized form input is rejected by request validation before auth checks."""
    client, session_factory = auth_required_client
    with session_factory() as s:
        create_local_user(
            s,
            username="bounded",
            display_name="Bounded Input",
            password="correct-passphrase-123",
        )
        s.commit()

    response = client.post(
        "/login",
        data={"username": "bounded", "password": "x" * 257},
        follow_redirects=False,
    )
    assert response.status_code == 422
    assert "lms_session" not in client.cookies


def test_logout_clears_session(
    auth_required_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = auth_required_client
    with session_factory() as s:
        create_local_user(s, username="carol", display_name="Carol", password="secret-passphrase")
        s.commit()

    client.post("/login", data={"username": "carol", "password": "secret-passphrase"})
    assert "lms_session" in client.cookies

    logout = client.post("/logout", follow_redirects=False)
    assert logout.status_code == 303
    assert logout.headers["location"] == "/login"

    # Subsequent protected requests fail again.
    response = client.get("/protected-api", headers={"Accept": "application/json"})
    assert response.status_code == 401


def test_session_only_stores_user_id_not_pii(
    auth_required_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    """Session payloads must contain only the stable id, never username / display name / email.

    This guards a privacy property of the cookie design (see
    docs/architecture/auth.md). Starlette's SessionMiddleware encodes the
    session as ``base64(json(payload)).timestamp.signature`` using
    :class:`itsdangerous.TimestampSigner`. We verify the signature and
    recover the JSON payload to inspect its keys.
    """
    import base64
    import json

    import itsdangerous

    client, session_factory = auth_required_client
    with session_factory() as s:
        create_local_user(
            s,
            username="dave",
            display_name="Dave the Privacy-Concerned",
            email="dave@example.test",
            password="dave-pass-1234",
        )
        s.commit()

    client.post("/login", data={"username": "dave", "password": "dave-pass-1234"})
    cookie = client.cookies.get("lms_session")
    assert cookie is not None

    signer = itsdangerous.TimestampSigner("test-key-not-for-prod")
    raw = signer.unsign(cookie, max_age=60 * 60 * 24 * 14)
    payload = json.loads(base64.b64decode(raw))
    assert isinstance(payload, dict)
    # Only the user id is stored. No username, display_name, or email.
    assert set(payload.keys()) == {SESSION_USER_ID_KEY}


def test_deleted_user_session_clears_cookie_and_reauthenticates(
    auth_required_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = auth_required_client
    with session_factory() as s:
        user = create_local_user(
            s,
            username="erin",
            display_name="Erin Deleted",
            password="erin-passphrase-1234",
        )
        user_id = user.id
        s.commit()

    login = client.post(
        "/login",
        data={"username": "erin", "password": "erin-passphrase-1234"},
        follow_redirects=False,
    )
    assert login.status_code == 303
    assert "lms_session" in client.cookies

    with session_factory() as s:
        user = s.get(User, user_id)
        assert user is not None
        s.delete(user)
        s.commit()

    response = client.get(
        "/protected-api",
        headers={"Accept": "application/json"},
        follow_redirects=False,
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required."}
    assert "lms_session" not in client.cookies
