"""Deployment contract tests for issue #180.

These tests keep the Render/Compose/auth deployment artifacts from drifting
away from the documented deploy path. They intentionally avoid invoking Docker
or Render; CI can run them with the normal unit suite.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]


def _load_yaml(path: str) -> dict[str, Any]:
    data = yaml.safe_load((ROOT / path).read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _render_env_map(service: dict[str, Any]) -> dict[str, dict[str, Any]]:
    env_vars = service.get("envVars")
    assert isinstance(env_vars, list)
    return {str(row["key"]): row for row in env_vars}


def test_render_blueprint_provisions_auth_gated_web_and_postgres() -> None:
    blueprint = _load_yaml("render.yaml")

    services = blueprint.get("services")
    databases = blueprint.get("databases")
    assert isinstance(services, list) and len(services) == 1
    assert isinstance(databases, list) and len(databases) == 1

    web = services[0]
    db = databases[0]
    assert web["type"] == "web"
    assert web["name"] == "learning-management-system"
    assert web["runtime"] == "python"
    assert web["healthCheckPath"] == "/health"
    assert web["startCommand"] == "uvicorn lms.main:app --host 0.0.0.0 --port $PORT"
    assert web["preDeployCommand"] == "python -m alembic.config upgrade head"

    assert db["name"] == "lms-db"
    assert db["databaseName"] == "lms"
    assert db["plan"] != "free"

    env = _render_env_map(web)
    assert env["DATABASE_URL"]["fromDatabase"] == {
        "name": "lms-db",
        "property": "connectionString",
    }
    assert env["AUTH_REQUIRED"]["value"] == "true"
    assert env["ENABLE_LOCAL_IDENTITY_ROUTES"]["value"] == "false"
    assert env["AUTH_SECRET_KEY"]["generateValue"] is True

    for secret_name in ("CLAUDE_API_STRANSKE", "LANGSMITH_API_KEY", "LLM_DAILY_BUDGET_USD"):
        assert env[secret_name]["sync"] is False


def test_compose_stack_matches_local_deployment_contract() -> None:
    compose = _load_yaml("docker-compose.yml")

    services = compose["services"]
    app = services["app"]
    db = services["db"]

    assert db["image"].startswith("postgres:")
    assert db["environment"] == {
        "POSTGRES_USER": "lms",
        "POSTGRES_PASSWORD": "lms",
        "POSTGRES_DB": "lms",
    }
    assert db["healthcheck"]["test"] == ["CMD-SHELL", "pg_isready -U lms -d lms"]

    assert app["build"] == {"context": ".", "dockerfile": "Dockerfile"}
    assert app["depends_on"]["db"]["condition"] == "service_healthy"
    assert app["env_file"] == [{"path": ".env", "required": False}]
    assert app["environment"]["DATABASE_URL"].startswith("${DATABASE_URL:-postgresql+psycopg://")
    assert app["environment"]["AUTH_REQUIRED"] == "${AUTH_REQUIRED:-false}"
    assert app["environment"]["AUTH_SECRET_KEY"] == (
        "${AUTH_SECRET_KEY:-dev-secret-do-not-use-in-production}"
    )
    assert app["environment"]["ENABLE_LOCAL_IDENTITY_ROUTES"] == (
        "${ENABLE_LOCAL_IDENTITY_ROUTES:-true}"
    )

    command_text = "\n".join(app["command"])
    assert "alembic upgrade head" in command_text
    assert "uvicorn lms.main:app --host 0.0.0.0 --port 8000 --reload" in command_text


def test_dockerfile_runtime_matches_compose_and_render_entrypoints() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "ARG PYTHON_IMAGE=python:" in dockerfile
    assert "uv pip sync requirements.lock" in dockerfile
    assert "pip install --no-cache-dir --no-deps -e ." in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert "http://localhost:8000/health" in dockerfile
    assert "uvicorn lms.main:app --host 0.0.0.0 --port ${PORT:-8000}" in dockerfile


def test_deployment_docs_cover_bootstrap_plan_tradeoffs_and_local_auth() -> None:
    deployment_doc = (ROOT / "docs/development/deployment.md").read_text(encoding="utf-8")
    local_setup_doc = (ROOT / "docs/development/local-setup.md").read_text(encoding="utf-8")
    auth_doc = (ROOT / "docs/architecture/auth.md").read_text(encoding="utf-8")

    assert "python -m lms auth create-user" in deployment_doc
    assert "AUTH_REQUIRED=true" in deployment_doc
    assert "preDeployCommand: alembic upgrade head" in deployment_doc
    assert "basic-256mb" in deployment_doc
    assert "pg_dump" in deployment_doc and "pg_restore" in deployment_doc

    assert "docker compose up --build" in local_setup_doc
    assert "AUTH_REQUIRED=true" in local_setup_doc
    assert "python -m lms auth create-user" in local_setup_doc
    assert "Postgres 16" not in local_setup_doc

    assert "Argon2id password authentication" in auth_doc
    assert "Starlette `SessionMiddleware`" in auth_doc
    assert "lms auth set-password" in auth_doc
