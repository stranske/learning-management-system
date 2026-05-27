# Workloop State

## 2026-05-27T05:1xZ - opener materialized PR for #110 author UI

- Automation: `pd-workloop-resume` (Claude Code opener lane), neutral Code workspace.
- Source issue: [#110](https://github.com/stranske/learning-management-system/issues/110) `Build authoring UI for goals, graph, and prompts` (priority:normal, milestone:M6, repo-review-approved).
- Branch: `claude/issue-110-author-learning-objects` off `origin/main` `470e449`.
- Selection: oldest unlinked normal-tier issue. High #121 deferred (M6 acceptance gate depends on the still-open M6 surfaces #110-#120). #106/#1075 excluded (already implemented/linked).
- Implementation (Surface 3 + Surface 4):
  - New `src/lms/ui/author.py` FastAPI router (`/app/author` landing + `/app/author/{goals,knowledge,prompts}` GET, `/app/author/knowledge/nodes`, `/app/author/knowledge/edges`, `/app/author/goals`, `/app/author/prompts` POST). Hand-built HTML via `render_page`/`empty_state`, matching `ui/api.py`.
  - Reuses existing repositories only: `graphs.repository` (node/edge create, cross-scope edges rejected by the existing `is_graph_reference` rule), `learners.repository` (goal create requires published target nodes), `prompts.repository` (draft prompt create requires published linked node + >=1 source ref), `sources.repository` (drift status display).
  - Forms enforce ownership_scope, show prompt provenance + source drift, render validation feedback (draft-node, missing-source, cross-scope) as `aria-invalid` notices, and show empty states. No course/module/lesson container text.
  - Wired router in `src/lms/main.py`; removed the old `/app/author` stub from `src/lms/ui/api.py`; updated `tests/ui/test_app_shell.py` (author surface is now implemented, not an empty stub).
- Tests: `tests/ui/test_author_learning_objects.py` -> 4 tests incl. the two required acceptance tests; full `tests/ui/` -> 14 passed; ruff check + format clean; mypy clean; author.py 98% / api.py 96% line coverage under the ui suite.
- Next action: keepalive owns CI/check follow-up; closer owns post-merge verification.

- Automation: `pd-workloop-resume` (codex opener lane).
- Source repo: `stranske/learning-management-system`.
- Source issue: [#106](https://github.com/stranske/learning-management-system/issues/106) `Accept case work products as transfer evidence`.
- PR: [#145](https://github.com/stranske/learning-management-system/pull/145) `Issue #106: Accept case work products as transfer evidence`.
- Branch: `claude/issue-106-case-work-products`.
- Recovery trigger:
  - Post-open cap-health showed LMS #145 as `runner-failed` after keepalive/Gate evidence.
  - Direct Gate log for run `26490283524` showed five deterministic migration failures from Alembic multiple heads: `20260527_0027_case_work_products` and `20260527_0027_merge_revision_requests_llm_feedback_events`.
- Fix:
  - Created a clean automation clone at `~/.codex/automations/pd-workloop-resume/worktrees/lms-issue-106-recovery` because the older worktree's git metadata was not writable.
  - Rebased `claude/issue-106-case-work-products` onto `origin/main` after LMS #144 merged.
  - Repointed `alembic/versions/20260527_0027_case_work_products.py` `down_revision` to `20260527_0027_merge_revision_requests_llm_feedback_events`.
  - Committed `60064d0` (`Issue #106: rebase case work migration onto LLM feedback head`) and force-pushed with lease to the existing PR branch.
- Validation:
  - `alembic heads` -> single head `20260527_0027_case_work_products`.
  - `pytest tests/evidence/test_attempts_migration.py::test_alembic_upgrade_head_creates_attempts_table tests/evidence/test_attempts_migration.py::test_alembic_upgrade_head_creates_evidence_records_table tests/llm/test_llm_sessions_migration.py::test_alembic_upgrade_head_creates_llm_sessions_table tests/llm/test_llm_sessions_migration.py::test_llm_sessions_trace_class_constraint_rejects_unknown_value tests/scheduling/test_review_queue.py::test_alembic_upgrade_head_creates_review_queue_items_table -q --no-cov` -> 5 passed.
  - `DATABASE_URL=sqlite:////tmp/lms-106-recovery-*.sqlite alembic upgrade head` -> passed.
  - `ruff check alembic/versions/20260527_0027_case_work_products.py` -> passed.
  - `ruff format --check alembic/versions/20260527_0027_case_work_products.py` -> passed.
- Post-push state:
  - Fresh PR head `60064d0`; PR remains non-draft with `agent:claude`, `agents:keepalive`, `autofix`, `agent:retry`, `repo-review-approved`, `priority:normal`, `milestone:M5`.
  - Cap-health at `2026-05-27T04:20:29Z` classified #145 as `draining` with active Gate evidence after the push.
- Next action: keepalive owns CI/check follow-up for PR #145.
