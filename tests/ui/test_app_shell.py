"""Contract tests for the shared web prototype shell."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker


def test_app_shell_uses_documented_routes_and_mobile_viewport(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _session_factory = api_client

    response = client.get("/app/learner")

    assert response.status_code == 200
    html = response.text
    assert 'name="viewport"' in html
    assert 'href="/static/ui/pico.min.css"' in html
    assert 'href="/static/ui/app.css"' in html
    assert 'href="/manifest.webmanifest"' in html
    assert 'navigator.serviceWorker.register("/service-worker.js")' in html
    assert 'href="/app/learner" aria-current="page"' in html
    assert 'href="/app/author"' in html
    assert 'href="/app/support"' in html
    assert 'href="/app/admin"' in html


def test_app_shell_empty_surfaces_are_available(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _session_factory = api_client

    for route, heading in [
        ("/app/support", "Support"),
        ("/app/admin", "Admin"),
    ]:
        response = client.get(route)

        assert response.status_code == 200
        assert f"<h1>{heading}</h1>" in response.text
        assert "empty-state" in response.text


def test_app_shell_author_surface_links_authoring_routes(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _session_factory = api_client

    response = client.get("/app/author")

    assert response.status_code == 200
    assert "<h1>Author</h1>" in response.text
    assert 'href="/app/author/goals"' in response.text
    assert 'href="/app/author/knowledge"' in response.text
    assert 'href="/app/author/prompts"' in response.text
