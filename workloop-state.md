# stranske/learning-management-system

## 2026-05-25T07:50:00Z - opener (claude_code) materialized LMS #7 lint/format/typecheck/test wiring

- Automation: `handoff-claude-opener` / `claude_code` opener lane.
- Repo: `stranske/learning-management-system`.
- Issue: [#7](https://github.com/stranske/learning-management-system/issues/7) — `Wire lint, formatting, typing, tests, and CI` (priority:high, milestone:M1, repo-review-approved).
- Branch: `claude/issue-7-wire-lint-format-typecheck-tests-ci`.
- Worktree: `/tmp/lms-issue-7-claude` (fresh clone; the canonical Code/learning-management-system checkout has unrelated untracked dirty state).

### Scope (matches issue acceptance criteria)

- Verify the existing `[tool.ruff]`, `[tool.black]`, `[tool.mypy]`, and `[tool.pytest.ini_options]` sections in `pyproject.toml` match the reusable Python CI invocations.
- Add a `Makefile` with `lint`, `format`, `format-check`, `typecheck`, `test`, and `check` targets that mirror the CI commands locally.
- Document the local check entry points in `docs/development/local-checks.md`.
- Keep `[tool.coverage.report].fail_under` at the template default of `80`.
- Leave `.github/workflows/ci.yml` (template-provided thin caller) untouched.

### Changes

- `pyproject.toml`: removed the unused `[[tool.mypy.overrides]] module = "tests.*"` block (CI only checks `src`; the override emitted a `note: unused section(s)`). Added a comment explaining why `target-version` stays at `["py312"]` to avoid Black's AST safety-check warning on 3.12 runners.
- `Makefile` (new): canonical local-check entry points. Variables `PYTHON`/`RUFF`/`BLACK`/`MYPY`/`PYTEST` are overridable. `RUFF_EXCLUDES` and `BLACK_EXCLUDES` match the reusable workflow.
- `docs/development/local-checks.md` (new): documents the Makefile contract, the CI parity rationale, and the coverage minimum.
- `tests/test_makefile_targets.py` (new): smoke-checks that the Makefile exposes the required `.PHONY` targets, every target has a recipe or prerequisite list, and `make check` depends on `lint`, `format-check`, `typecheck`, and `test`.

### Validation

- `make lint` → `ruff check --extend-exclude .workflows-lib .` → All checks passed.
- `make format-check` → `black --check --line-length 100 --exclude '(\.venv|\.workflows-lib|node_modules)' .` → 68 files left unchanged.
- `make typecheck` → `mypy --config-file pyproject.toml --exclude .workflows-lib src` → Success: no issues found in 15 source files.
- `make test` → `pytest` → 11 passed; coverage 88.24%, above the 80% template minimum.
- `make check` end-to-end finished in ~2s (well under the 2-minute ceiling from the acceptance criteria).

### Next action

- `pr_opened`: open ready-for-review PR for issue #7 with `agent:claude`, `agents:keepalive`, `autofix`, `priority:high`, `repo-review-approved` labels; rely on Gate + keepalive (reusable-claude-run.yml) for further CI/triage. Opener will not chase the PR further after `pr_opened`.
