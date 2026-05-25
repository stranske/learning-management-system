# Backend Setup

The LMS backend is Postgres-first. Local development uses SQLAlchemy for
runtime sessions and Alembic for schema migrations.

## Environment

Create a local `.env` from the example and set `DATABASE_URL` to a Postgres
database owned by your local development user:

```bash
cp .env.example .env
createdb lms_dev
```

The placeholder URL in `.env.example` connects as your local OS user without an
embedded password (which keeps real credentials out of the repository):

```text
DATABASE_URL=postgresql+psycopg://localhost:5432/lms_dev
```

If you prefer a dedicated Postgres role, create it first and update
`DATABASE_URL` in your private `.env` accordingly. For example:

```bash
createuser lms --pwprompt
createdb --owner=lms lms_dev
```

Then set `DATABASE_URL=postgresql+psycopg://lms:<your-password>@localhost:5432/lms_dev`
in `.env` (never commit a real password).

## Migrations

Run the baseline migration against a fresh database:

```bash
uv run alembic upgrade head
```

Reset the database to the pre-baseline state when you need to recreate the
schema from scratch:

```bash
uv run alembic downgrade base
```

The first revision is intentionally empty. It establishes a durable migration
anchor so later Milestone 1 and Milestone 2 issues can add tables without
recreating Alembic configuration.

## Tests

The shared `db_session` fixture in `tests/conftest.py` creates an isolated
SQLAlchemy session for model-level tests. It uses an in-memory SQLite engine so
tests can exercise session behavior without requiring every unit test to own a
Postgres service. Postgres remains the runtime and migration target.
