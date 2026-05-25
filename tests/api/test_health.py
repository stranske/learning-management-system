"""Tests for the LMS /health endpoint."""

from __future__ import annotations

from fastapi.testclient import TestClient

from lms import APP_NAME, __version__, create_app


def test_health_returns_ok() -> None:
    """GET /health returns HTTP 200 with JSON containing status=ok."""
    client = TestClient(create_app())
    response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["app"] == APP_NAME
    assert payload["version"] == __version__


def test_openapi_available() -> None:
    """OpenAPI schema is exposed by the FastAPI app for development docs."""
    client = TestClient(create_app())
    response = client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert schema["info"]["title"] == "Learning Management System"
    assert "/auth/users" in schema["paths"]
    assert "/health" in schema["paths"]
    assert "/learners" in schema["paths"]
