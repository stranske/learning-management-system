# stranske/learning-management-system

## 2026-05-25T08:12:00Z - opener opened PR #43 for issue #9

- Automation: `codex` opener lane.
- Selected issue: #9, "Add research YAML schemas and validator".
- Branch: `codex/issue-9-research-yaml-schemas-validator`.
- PR: #43, https://github.com/stranske/learning-management-system/pull/43.
- PR routing: non-draft with `agent:codex`, `agent:retry`, `agents:keepalive`, `autofix`, `priority:high`, `repo-review-approved`, and `milestone:M2`.
- Post-open hygiene: after the first workflow batch, removed a mechanical `needs-human` label from PR #43 because fresh Gate activity existed and no concrete human decision was evident.
- Related cap hygiene before selection: removed stale `needs-human` from PR #42 and added `agent:retry`; fresh cap-health reported PRs #36, #40, and #42 all draining, raw cap below five.
- Scoped blocker recorded before selection: issue #8 waits for PR #40 database session/Alembic baseline to land so the auth placeholder does not duplicate migration/session work.

## Implementation

- Added build-time research registry schemas in `src/lms/research_registry/`.
- Seeded `docs/research/registry/{principles,claims,evidence-sources}.yml` with Chapter 1 and Section 2.3 records.
- Added `lms validate-research-registry` CLI command and project script entry.
- Added focused validator, enum, CLI, and no-runtime-route tests.
- Added explicit `PyYAML` runtime dependency and refreshed lock files.

## Validation

- `python -m ruff check src tests`
- `python -m black --check src tests`
- `python -m mypy src` (passes; existing pyproject note: unused `tests.*` override)
- `PYTHONPATH=src python -m lms validate-research-registry`
- `python -m pytest` -> 14 passed, coverage 91.06%

## Next action

Wait for Gate and keepalive on PR #43.
