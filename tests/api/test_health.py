"""Tests for the LMS /health endpoint."""

from __future__ import annotations

from fastapi.testclient import TestClient

from lms import APP_NAME, __version__, create_app


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


def test_local_identity_openapi_enabled_explicitly() -> None:
    """Local identity routes are available only when explicitly enabled."""
    with TestClient(create_app(enable_local_identity_routes=True)) as client:
        response = client.get("/openapi.json")
        assert response.status_code == 200
        schema = response.json()
        assert "/auth/users" in schema["paths"]
        assert "/learners" in schema["paths"]
