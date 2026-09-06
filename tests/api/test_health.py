"""Tests for the LMS /health endpoint."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from lms import APP_NAME, __version__, create_app
from lms.settings import get_settings


@pytest.fixture(autouse=True)
def local_auth_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Isolate factory settings from ambient configuration and other tests."""
    monkeypatch.setenv("AUTH_REQUIRED", "false")
    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()


def test_health_returns_ok() -> None:
    """GET /health returns HTTP 200 with JSON containing status=ok."""
    with TestClient(create_app()) as client:
        response = client.get("/health")
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "ok"
        assert payload["app"] == APP_NAME
        assert payload["version"] == __version__


def test_openapi_available() -> None:
    """OpenAPI schema is exposed by the FastAPI app for development docs."""
    with TestClient(create_app()) as client:
        response = client.get("/openapi.json")
        assert response.status_code == 200
        schema = response.json()
        assert schema["info"]["title"] == "Learning Management System"
        assert "/health" in schema["paths"]
        assert "/auth/users" not in schema["paths"]
        assert "/learners" not in schema["paths"]


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/docs/oauth2-redirect"])
def test_documentation_available_in_local_development(path: str) -> None:
    with TestClient(create_app()) as client:
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]


@pytest.mark.parametrize("path", ["/openapi.json", "/docs", "/redoc", "/docs/oauth2-redirect"])
def test_openapi_hidden_when_auth_required(monkeypatch: pytest.MonkeyPatch, path: str) -> None:
    """Deployed factory settings hide docs and schema without dependency overrides."""
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    get_settings.cache_clear()
    with TestClient(create_app()) as client:
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 404
        assert client.get("/health").status_code == 200


def test_local_identity_openapi_enabled_explicitly() -> None:
    """Local identity routes are available only when explicitly enabled."""
    with TestClient(create_app(enable_local_identity_routes=True)) as client:
        response = client.get("/openapi.json")
        assert response.status_code == 200
        schema = response.json()
        assert "/auth/users" in schema["paths"]
        assert "/learners" in schema["paths"]
