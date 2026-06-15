"""Helpers for the Alembic version-tracking table (``alembic_version``).

Alembic hardcodes ``alembic_version.version_num`` as ``VARCHAR(32)``
(``alembic.ddl.impl.DefaultImpl.version_table_impl``). This project uses long,
descriptive revision identifiers — up to 57 characters, e.g.
``20260527_0027_merge_revision_requests_llm_feedback_events`` — which overflow
that column on Postgres, raising
``psycopg.errors.StringDataRightTruncation: value too long for type character
varying(32)`` partway through ``alembic upgrade head``.

SQLite does **not** enforce ``VARCHAR`` length, so the SQLite-backed test suite
never exercised this limit; only the deployed Postgres database did, which is
why every Render pre-deploy migration failed at the first >32-char revision.
"""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

# Generous headroom over the current longest revision id (57 chars).
VERSION_NUM_LENGTH = 255


def ensure_version_table_width(connection: Connection) -> None:
    """Ensure ``alembic_version.version_num`` is wide enough for our revisions.

    Widens an existing column, or pre-creates the table wide so Alembic reuses
    it instead of falling back to its 32-char default. Postgres-only (SQLite
    ignores ``VARCHAR`` length) and idempotent, so it is safe to call on every
    migration run and a no-op for the test suite's SQLite engine.
    """
    if connection.dialect.name != "postgresql":
        return

    if inspect(connection).has_table("alembic_version"):
        connection.execute(
            text(
                "ALTER TABLE alembic_version "
                f"ALTER COLUMN version_num TYPE VARCHAR({VERSION_NUM_LENGTH})"
            )
        )
    else:
        connection.execute(
            text(
                "CREATE TABLE alembic_version ("
                f"version_num VARCHAR({VERSION_NUM_LENGTH}) NOT NULL, "
                "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
            )
        )
    connection.commit()
