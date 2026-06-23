"""Regression tests for the documented Docker Compose local-dev stack."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from lms import create_app

ROOT = Path(__file__).resolve().parents[1]


def test_compose_uses_postgres_18_volume_root() -> None:
    """Postgres 18 must mount the named volume at /var/lib/postgresql."""
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))

    volumes = compose["services"]["db"]["volumes"]

    assert "lms_pg_data:/var/lib/postgresql" in volumes
    assert "lms_pg_data:/var/lib/postgresql/data" not in volumes


def test_dockerfile_runtime_imports_app_src() -> None:
    """The runtime image must import lms from /app/src, not stale /build/src."""
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "PYTHONPATH=/app/src" in dockerfile
    assert "COPY --from=builder /build /app" in dockerfile


def test_root_redirects_to_admin_entrypoint() -> None:
    """The base URL should not be a bare JSON 404 in local compose runs."""
    with TestClient(create_app(), follow_redirects=False) as client:
        response = client.get("/")

    assert response.status_code == 307
    assert response.headers["location"] == "/app/admin"


@pytest.mark.slow
def test_compose_stack_starts_and_serves_admin() -> None:
    """Opt-in end-to-end smoke for the documented docker compose up path."""
    if os.environ.get("LMS_RUN_COMPOSE_SMOKE") != "1":
        pytest.skip("set LMS_RUN_COMPOSE_SMOKE=1 to run the Docker Compose smoke test")
    if shutil.which("docker") is None:
        pytest.skip("docker is not installed")

    project = f"lms-compose-smoke-{os.getpid()}"
    command = ["docker", "compose", "-p", project]

    try:
        subprocess.run(
            [*command, "up", "-d", "--build", "--wait"],
            cwd=ROOT,
            check=True,
            timeout=240,
        )
        deadline = time.monotonic() + 60
        while True:
            health = subprocess.run(
                [*command, "exec", "-T", "app", "curl", "--fail", "http://localhost:8000/health"],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
                timeout=15,
            )
            admin = subprocess.run(
                [
                    *command,
                    "exec",
                    "-T",
                    "app",
                    "curl",
                    "--fail",
                    "http://localhost:8000/app/admin",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
                timeout=15,
            )
            if health.returncode == 0 and admin.returncode == 0:
                break
            if time.monotonic() >= deadline:
                raise AssertionError(
                    "compose stack did not serve /health and /app/admin\n"
                    f"health stdout={health.stdout}\nhealth stderr={health.stderr}\n"
                    f"admin stdout={admin.stdout}\nadmin stderr={admin.stderr}"
                )
            time.sleep(2)
    finally:
        subprocess.run([*command, "down", "-v"], cwd=ROOT, check=False, timeout=120)
