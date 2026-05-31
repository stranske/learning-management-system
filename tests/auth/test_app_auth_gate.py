"""Regression test: ``create_app()`` actually wires ``require_authenticated_user``.

The 2026-05-30 audit (docs/audits/2026-05-30-comprehensive-audit.md) found the
auth dependency was *defined* but attached to zero routers, so every endpoint was
reachable without credentials even when ``AUTH_REQUIRED=true`` on the deployed
instance. ``tests/auth/test_authenticated_session.py`` only exercises the
dependency on a minimal hand-built app, so it could not catch the missing wiring
on the real factory. This drives ``create_app()`` itself.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import lms.audit.models  # noqa: F401  # register Base.metadata
from lms.db.base import Base
from lms.db.session import get_session
from lms.main import create_app
from lms.settings import Settings, get_settings

pytestmark = pytest.mark.slow


@pytest.fixture
def auth_required_app_client() -> Generator[TestClient, None, None]:
    """The real ``create_app()`` factory with ``auth_required=True`` forced on.

    Only the settings and DB session are overridden; the router wiring under test
    is exactly what production builds.
    """
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    def override_get_session() -> Generator[Session, None, None]:
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app = create_app(enable_local_identity_routes=False)
    app.dependency_overrides[get_settings] = lambda: Settings(
        auth_required=True, auth_secret_key="test-secret-not-for-prod"
    )
    app.dependency_overrides[get_session] = override_get_session

    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_protected_api_route_requires_auth(auth_required_app_client: TestClient) -> None:
    """A router mounted by create_app() returns 401 for an unauthenticated API call."""
    response = auth_required_app_client.get(
        "/audit/events",
        headers={"Accept": "application/json"},
        follow_redirects=False,
    )
    assert response.status_code == 401


def test_health_route_stays_public(auth_required_app_client: TestClient) -> None:
    """Health check is on the allowlist and must remain reachable without auth."""
    response = auth_required_app_client.get("/health")
    assert response.status_code == 200


def test_login_route_is_not_gated(auth_required_app_client: TestClient) -> None:
    """The login page must not sit behind the gate, else there is no way to log in."""
    response = auth_required_app_client.get(
        "/login", headers={"Accept": "text/html"}, follow_redirects=False
    )
    # Not an auth failure (401) and not a redirect-to-login loop (302).
    assert response.status_code not in (401, 302)
