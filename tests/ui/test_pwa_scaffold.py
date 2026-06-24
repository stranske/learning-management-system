"""Contract tests for PWA scaffold assets."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker


def test_manifest_and_service_worker_are_served(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _session_factory = api_client

    manifest_response = client.get("/manifest.webmanifest")
    service_worker_response = client.get("/service-worker.js")
    css_response = client.get("/static/ui/pico.min.css")
    tokens_response = client.get("/static/ui/tokens.css")
    components_response = client.get("/static/ui/components.css")
    reconcile_response = client.get("/static/ui/ds-reconcile.css")
    icon_response = client.get("/static/ui/icons/icon-192.svg")

    assert manifest_response.status_code == 200
    assert manifest_response.json()["start_url"] == "/app/learner"
    assert service_worker_response.status_code == 200
    assert "skipWaiting" in service_worker_response.text
    assert css_response.status_code == 200
    assert "--pico-primary" in css_response.text
    assert tokens_response.status_code == 200
    assert ".theme-paper" in tokens_response.text
    assert components_response.status_code == 200
    assert ".ds .panel" in components_response.text
    assert reconcile_response.status_code == 200
    assert "--lms-accent" in reconcile_response.text
    assert icon_response.status_code == 200
    assert "<svg" in icon_response.text
