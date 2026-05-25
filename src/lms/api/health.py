"""Health-check endpoint."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from lms import APP_NAME, __version__

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """Payload returned by ``GET /health``."""

    status: str
    app: str
    version: str


@router.get("/health", response_model=HealthResponse)
def get_health() -> HealthResponse:
    """Return service status, app name, and version."""
    return HealthResponse(status="ok", app=APP_NAME, version=__version__)
