"""FastAPI application factory for the LMS backend."""

from __future__ import annotations

from fastapi import FastAPI

from lms.api.health import router as health_router
from lms.auth.api import router as auth_router
from lms.learners.api import router as learners_router


def create_app() -> FastAPI:
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
    app.include_router(auth_router)
    app.include_router(health_router)
    app.include_router(learners_router)
    return app


app = create_app()
