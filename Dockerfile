# LMS Dockerfile — two-stage build for FastAPI + uvicorn.
#
# Stage 1 (builder) installs build tools, creates a virtualenv, and uses uv
# to install the locked dependency set + the project itself in editable mode.
# Stage 2 (runtime) is a slim image that only carries the venv + sources +
# the runtime libraries needed by uvicorn/psycopg.
#
# The image is intentionally generic so it works both for:
#   - local dev via ``docker compose up`` (see docker-compose.yml)
#   - Render's optional container build path (Render also has a native
#     Python runtime via render.yaml; the Dockerfile is the portable fallback)
ARG PYTHON_IMAGE=python:3.14-slim

# -----------------------------------------------------------------------------
# Builder stage
# -----------------------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS builder

ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        git && \
    rm -rf /var/lib/apt/lists/*

ENV VIRTUAL_ENV=/opt/venv
RUN python -m venv ${VIRTUAL_ENV}
ENV PATH="${VIRTUAL_ENV}/bin:${PATH}"

WORKDIR /build

# Copy lock + project metadata first so the dependency layer caches across
# source edits.
COPY pyproject.toml requirements.lock ./

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir setuptools wheel uv && \
    uv pip sync requirements.lock

# Copy the rest of the repo and install the package itself (no deps — they
# were locked above, and we want a strict lock-respecting install).
COPY . .
RUN pip install --no-cache-dir --no-deps -e .

# -----------------------------------------------------------------------------
# Runtime stage
# -----------------------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS runtime

ARG DEBIAN_FRONTEND=noninteractive

# Runtime-only system deps: curl for HEALTHCHECK, libpq for psycopg's binary
# wheel (psycopg[binary] ships the lib but on slim images we still want it
# available system-wide for any callers that bypass the wheel).
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl \
        libpq5 && \
    rm -rf /var/lib/apt/lists/*

ENV VIRTUAL_ENV=/opt/venv
COPY --from=builder ${VIRTUAL_ENV} ${VIRTUAL_ENV}
ENV PATH="${VIRTUAL_ENV}/bin:${PATH}"
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY --from=builder /build /app

# The builder ran ``pip install -e .`` from /build, so the editable record
# (__editable__.lms-*.pth) points at the build-time path /build/src, which does
# not exist in this runtime image (sources were copied to /app). Put the real
# package root on the import path so ``lms`` is importable for both
# ``alembic upgrade head`` and ``uvicorn lms.main:app``. This path also matches
# the docker-compose ``./src:/app/src`` bind mount, so --reload still works.
ENV PYTHONPATH=/app/src

# Drop privileges before exposing the runtime surface.
RUN useradd --create-home --uid 1001 appuser && \
    chown -R appuser:appuser /app /opt/venv
USER appuser

EXPOSE 8000

# The /health route is registered by lms.api.health.router. Use it instead of
# pinging /, which currently 404s outside the UI app surfaces.
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl --fail http://localhost:8000/health || exit 1

# Render injects $PORT; locally we default to 8000 via docker-compose.
# Use a shell form so $PORT expands inside the entrypoint.
CMD ["sh", "-c", "uvicorn lms.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
