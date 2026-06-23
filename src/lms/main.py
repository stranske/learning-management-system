"""FastAPI application factory for the LMS backend."""

from __future__ import annotations

from importlib.resources import files

from fastapi import Depends, FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from lms.api.audit import router as audit_router
from lms.api.health import router as health_router
from lms.api.inspect import router as inspect_router
from lms.auth.api import router as auth_router
from lms.auth.login import require_authenticated_user
from lms.auth.login import router as login_router
from lms.capability.api import router as capability_router
from lms.cases.api import router as cases_router
from lms.competencies.api import router as competencies_router
from lms.evidence.api import router as attempts_router
from lms.feedback.api import router as feedback_router
from lms.graphs.api import router as graphs_router
from lms.learners.api import router as learners_router
from lms.llm.api import router as llm_router
from lms.mastery.api import router as mastery_router
from lms.prompts.api import router as prompts_router
from lms.scheduling.api import router as review_queue_router
from lms.settings import get_settings
from lms.sources.api import router as sources_router
from lms.ui.api import router as learner_ui_router
from lms.ui.attempts import router as attempt_flow_router
from lms.ui.capability_gap import router as capability_ui_router
from lms.ui.cases import router as learner_cases_ui_router
from lms.ui.feedback import router as learner_feedback_ui_router
from lms.ui.graph_design import router as graph_design_ui_router
from lms.ui.llm_study import router as llm_study_ui_router
from lms.ui.support_admin import router as support_admin_ui_router


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
    settings = get_settings()
    if enable_local_identity_routes is None:
        enable_local_identity_routes = settings.enable_local_identity_routes
    app.state.enable_local_identity_routes = enable_local_identity_routes

    # SessionMiddleware ships signed cookies via itsdangerous. It is mounted
    # unconditionally so /login can read/write session state even in local
    # dev where ``auth_required`` is false; the gate that forces a login is
    # the require_authenticated_user dependency, not this middleware.
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.auth_secret_key,
        session_cookie=settings.session_cookie_name,
        max_age=settings.session_max_age_seconds,
        same_site="lax",
        # Render serves over HTTPS in production; behind its TLS terminator
        # FastAPI itself sees plain HTTP, so we only flip ``https_only`` on
        # when auth is required (i.e. deployed mode). Local-dev keeps cookies
        # working on http://localhost.
        https_only=settings.auth_required,
    )

    # The login/logout routes are always mounted; the form is reachable on
    # local dev too so the flow can be exercised end-to-end without flipping
    # AUTH_REQUIRED on. The require_authenticated_user dependency is what
    # actually gates downstream routes when AUTH_REQUIRED is true.
    app.include_router(login_router)

    # Every router below the login/health/static allowlist is gated by
    # require_authenticated_user. That dependency is a no-op in local-dev/test
    # mode (auth_required=False returns the local-dev user, preserving existing
    # behavior) and enforces a 401 (JSON) / 302-to-login (HTML) when
    # AUTH_REQUIRED=true on the deployed instance. Attaching it here is what
    # actually closes the gate — defining the dependency alone left every
    # endpoint reachable without credentials.
    auth = [Depends(require_authenticated_user)]

    if enable_local_identity_routes:
        # Local identity bootstrap endpoints must stay reachable without the
        # auth gate they are intended to initialize.
        app.include_router(auth_router)
        app.include_router(learners_router, dependencies=auth)

    @app.get("/", include_in_schema=False)
    def root_redirect() -> RedirectResponse:
        """Send the base URL to the local admin entry point."""
        return RedirectResponse(url="/app/admin", status_code=307)

    app.include_router(health_router)
    app.include_router(inspect_router, dependencies=auth)
    app.include_router(audit_router, dependencies=auth)
    app.include_router(sources_router, dependencies=auth)
    app.include_router(graphs_router, dependencies=auth)
    app.include_router(prompts_router, dependencies=auth)
    app.include_router(attempts_router, dependencies=auth)
    app.include_router(feedback_router, dependencies=auth)
    app.include_router(cases_router, dependencies=auth)
    app.include_router(competencies_router, dependencies=auth)
    app.include_router(capability_router, dependencies=auth)
    app.include_router(mastery_router, dependencies=auth)
    app.include_router(review_queue_router, dependencies=auth)
    app.include_router(llm_router, dependencies=auth)
    app.include_router(learner_ui_router, dependencies=auth)
    app.include_router(attempt_flow_router, dependencies=auth)
    app.include_router(capability_ui_router, dependencies=auth)
    app.include_router(learner_cases_ui_router, dependencies=auth)
    app.include_router(learner_feedback_ui_router, dependencies=auth)
    app.include_router(graph_design_ui_router, dependencies=auth)
    app.include_router(llm_study_ui_router, dependencies=auth)
    app.include_router(support_admin_ui_router, dependencies=auth)
    static_path = files("lms.ui.static")
    app.mount("/static/ui", StaticFiles(directory=str(static_path)), name="ui-static")
    return app


app = create_app()
