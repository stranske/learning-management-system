# Audit Log

The LMS audit log captures every create/update on authoring records so future
institutional or evaluation scopes can replay history. The v1 implementation is
intentionally minimal: a single `audit_events` table with a recording helper
and a read-only HTTP surface.

## Audited entities

Importers and CRUD issues MUST call
`lms.audit.repository.record_audit_event(...)` whenever they create, update, or
delete one of the following entities:

- `KnowledgeNode`
- `KnowledgeEdge`
- `Prompt`
- `SourceReference`
- `Rubric` (future, added with the rubric model)

The canonical list lives in
`lms.audit.repository.AUDITED_ENTITY_TYPES`; keep that constant in sync if you
add a new audited entity.

## Recording an event

`record_audit_event` is a thin SQLAlchemy helper that adds and flushes a row
without committing. The caller owns the transaction (so the audit row commits
or rolls back with the surrounding business write).

```python
from lms.audit.repository import record_audit_event

record_audit_event(
    session,
    actor_id="user:alice",
    action="create",
    entity_type="SourceReference",
    entity_id="src-001",
    source_subsystem="research-importer",
    before_summary=None,
    after_summary={"title": "Quantum Mechanics, 3e"},
)
```

Field expectations:

- `actor_id` — string identifier for the human or system that initiated the
  action (e.g. `user:alice`, `system`, `importer:markdown`).
- `action` — short verb like `create`, `update`, `delete`, `publish`.
- `entity_type` — canonical model name (matches `AUDITED_ENTITY_TYPES`).
- `entity_id` — opaque identifier of the affected row (string).
- `source_subsystem` — short tag for the code path (`api`, `research-importer`,
  `graph-importer`, etc.).
- `before_summary` / `after_summary` — JSON-serialisable snapshots of the
  fields relevant to the action; either may be omitted.
- `occurred_at` — optional; defaults to the current UTC time.

## Reading events

`GET /audit/events` returns events in reverse chronological order. Query
parameters:

- `entity_type` — restrict to a single audited entity type.
- `actor_id` — restrict to a single actor.
- `limit` — page size (default 100, max 500).
