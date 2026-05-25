"""FastAPI application factory for the LMS backend."""

from __future__ import annotations

from fastapi import FastAPI

from lms.api.audit import router as audit_router
from lms.api.health import router as health_router
from lms.auth.api import router as auth_router
from lms.learners.api import router as learners_router
from lms.settings import get_settings


def create_app(*, enable_local_identity_routes: bool | None = None) -> FastAPI:
    """Create and configure the FastAPI application.

    The factory pattern keeps the module-level import side-effect free so tests
    can construct isolated app instances and so future configuration (settings,
    database session, LLM provider wiring) can be injected without rewriting
    the module shape.
    """
    app = FastAPI(
        title="Learning Management System",
        description="API-first backend for evidence-informed personal learning.",
        version="0.1.0",
    )
    if enable_local_identity_routes is None:
        enable_local_identity_routes = get_settings().enable_local_identity_routes

    if enable_local_identity_routes:
        app.include_router(auth_router)
        app.include_router(learners_router)

    app.include_router(health_router)
    app.include_router(audit_router)
    return app


app = create_app()
