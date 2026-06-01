# Local development setup

Two supported paths. Pick the one that matches your workflow.

## Option A: Docker Compose (fastest)

Requires Docker Desktop (or any container runtime + `docker compose`).

```bash
docker compose up --build
```

That single command:

1. Builds the LMS image from `Dockerfile`.
2. Starts a Postgres 16 container with a persistent volume (`lms_pg_data`).
3. Waits for Postgres to be healthy.
4. Runs `alembic upgrade head` against the new DB.
5. Starts uvicorn with `--reload` pointed at the bind-mounted `src/` tree, so
   edits in your editor reload automatically.

The app is then at <http://localhost:8000>. Health check: <http://localhost:8000/health>.

To reset the DB (drop the persistent volume):

```bash
docker compose down -v
```

### Surfacing the LLM key

`docker-compose.yml` reads a private `.env` file when present and also
forwards `CLAUDE_API_STRANSKE` from your shell env if it is set. The simplest
shell-only way:

```bash
export CLAUDE_API_STRANSKE='sk-ant-...'
docker compose up
```

Don't add `.env` to the repo. The Compose file already reads from your shell.

For repeated local work, create a private `.env` instead:

```bash
CLAUDE_API_STRANSKE=sk-ant-...
LANGSMITH_API_KEY=...
LLM_DAILY_BUDGET_USD=2.50
```

`.env` is gitignored and must stay local.

## Option B: Native venv

Requires Python 3.13 and a local Postgres (or just point `DATABASE_URL` at any
reachable Postgres instance).

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
# Point at your Postgres; the example below assumes the docker-compose db is up.
export DATABASE_URL='postgresql+psycopg://lms:lms@localhost:5432/lms'
alembic upgrade head
uvicorn lms.main:app --reload
```

## Toggling auth on locally

`AUTH_REQUIRED=false` by default — the local-dev shortcut user keeps working
and the login flow is reachable but optional. To exercise the production
behavior locally:

```bash
export AUTH_REQUIRED=true
export AUTH_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
# Create the first user (see docs/architecture/auth.md):
python -m lms auth create-user --username dev --display-name 'Dev' --password
# Then start the app and visit http://localhost:8000/login
```

The session cookie persists across requests in your browser; clear it (or
restart with a new `AUTH_SECRET_KEY`) to force a fresh login.

## Running tests

```bash
pytest
```

Tests run against an in-memory SQLite database via the fixtures in
`tests/conftest.py`. They don't need Postgres or the LLM key.
