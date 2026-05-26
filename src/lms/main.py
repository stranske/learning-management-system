"""FastAPI application factory for the LMS backend."""

from __future__ import annotations

from fastapi import FastAPI

from lms.api.audit import router as audit_router
from lms.api.health import router as health_router
from lms.api.inspect import router as inspect_router
from lms.auth.api import router as auth_router
from lms.evidence.api import router as attempts_router
from lms.graphs.api import router as graphs_router
from lms.learners.api import router as learners_router
from lms.llm.api import router as llm_router
from lms.mastery.api import router as mastery_router
from lms.prompts.api import router as prompts_router
from lms.scheduling.api import router as review_queue_router
from lms.settings import get_settings
from lms.sources.api import router as sources_router
from lms.ui.api import router as learner_ui_router


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
    app.include_router(inspect_router)
    app.include_router(audit_router)
    app.include_router(sources_router)
    app.include_router(graphs_router)
    app.include_router(prompts_router)
    app.include_router(attempts_router)
    app.include_router(mastery_router)
    app.include_router(review_queue_router)
    app.include_router(llm_router)
    app.include_router(learner_ui_router)
    return app


app = create_app()
