#!/usr/bin/env bash
# Compose smoke test for the local dev stack — guards issue #351.
#
# Brings the full ``docker compose`` stack up from a CLEAN volume and asserts
# the app starts end-to-end:
#   1. the db container stays up (postgres:18 volume path is correct),
#   2. ``GET /health`` becomes ready (the ``lms`` package is importable, so
#      ``alembic upgrade head`` + ``uvicorn lms.main:app`` start),
#   3. ``GET /app/admin`` returns 200 (an authenticated-dev UI surface renders),
#   4. ``GET /`` is not a bare 404 (the root landing is served).
#
# Exits non-zero on any failure and dumps container logs for triage. This is
# the runnable contract behind .github/workflows/compose-smoke.yml.
set -euo pipefail

PROJECT="${COMPOSE_SMOKE_PROJECT:-lms-compose-smoke}"
BASE_URL="${COMPOSE_SMOKE_URL:-http://127.0.0.1:8000}"
HEALTH_TIMEOUT="${COMPOSE_SMOKE_TIMEOUT:-180}"

compose() { docker compose -p "$PROJECT" "$@"; }
cleanup() { compose down -v --remove-orphans >/dev/null 2>&1 || true; }
trap cleanup EXIT

http_code() { curl -s -o /dev/null -w "%{http_code}" "${BASE_URL}$1"; }

echo "==> Clean slate (down -v)"
cleanup

echo "==> Build + start stack (up -d --build)"
compose up -d --build

echo "==> Wait for /health (timeout ${HEALTH_TIMEOUT}s)"
deadline=$(( SECONDS + HEALTH_TIMEOUT ))
until curl -fsS "${BASE_URL}/health" >/dev/null 2>&1; do
  if (( SECONDS >= deadline )); then
    echo "FAIL: /health did not become ready within ${HEALTH_TIMEOUT}s" >&2
    echo "----- db logs -----"  >&2; compose logs db  2>&1 | tail -30 >&2
    echo "----- app logs -----" >&2; compose logs app 2>&1 | tail -40 >&2
    exit 1
  fi
  sleep 3
done
echo "    /health ready"

fail=0

admin_code="$(http_code /app/admin)"
echo "    GET /app/admin -> ${admin_code}"
[ "$admin_code" = "200" ] || { echo "FAIL: /app/admin expected 200, got ${admin_code}" >&2; fail=1; }

root_code="$(http_code /)"
echo "    GET / -> ${root_code}"
[ "$root_code" != "404" ] || { echo "FAIL: / is a bare 404 (root landing missing)" >&2; fail=1; }

if [ "$fail" -ne 0 ]; then
  echo "----- app logs -----" >&2; compose logs app 2>&1 | tail -40 >&2
  exit 1
fi

echo "==> SMOKE PASS: clean-volume stack starts; /health ready; /app/admin 200; / not 404"
