# UX Review Log — learning-management-system

Diff-anchored record of UX Review (`/ux-review`) passes. Detailed artifacts live in `Orchestrator/ux_reviews/`.

## 2026-06-22 — Server-rendered FastAPI + Postgres (docker compose) — commit `bd33686` — overall 3.0/10 (gate FAIL)
- **Scope:** server-rendered role-based UI under `/app/<role>`. The documented `docker compose up` was **BROKEN** — needed two local patches (pg18 volume mount + `lms` PYTHONPATH) to start. UI reviewed via real browser (AUTH off in dev).
- **Coverage:** docker-compose run (broken) ✓; `/` (JSON 404) ✓; `/app/learner/llm-study` ✓ (clean form + privacy/trace explanations + good empty state); `/app/admin` ✓ (clean empty states + health). Other `/app/<role>` pages (feedback / author graph / support) + login not driven (need seed data).
- **Scores:** wired 4.0 / usability 4.0 / help_clarity 5.5 / workflow 3.5 — overall blocker-capped at 3.0 by the broken local stack + the root 404.
- **Headline:** the UI renders cleanly once running, but the documented local run path is doubly-broken (a Gate-1 runnability blocker).
- **Findings → filed:** local stack broken (pg18 volume + Dockerfile editable-install path) + root `/` JSON 404 → **#351** (all 5 panel findings map here).
- **Next focus:** after #351, seed data + drive the learner-feedback / author-graph / support surfaces; re-check the gate.
