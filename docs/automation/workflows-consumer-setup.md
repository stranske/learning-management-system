# Workflows Consumer Setup

Status: M0-002 pass complete (2026-05-25). Template diff verified; one missing file (`config/coverage-baseline.json`) was restored. This document records what arrived with the GitHub template, what was added per-repo for LMS, and where each surface is owned.

## Provenance

This repository was created via:

```sh
gh repo create stranske/learning-management-system \
  --template stranske/Template \
  --public
```

GitHub's template-repository mechanism delivers an initial copy of every file under `stranske/Template`. The consumer-template content in `stranske/Workflows/templates/consumer-repo/` is the source-of-truth for the synced surfaces (agent workflows, codex prompts, base instructions, helper scripts, and docs). After the repo is registered with `stranske/Workflows`, the periodic `maint-68-sync-consumer-repos.yml` workflow upstream keeps the synced files current.

This issue (`#2 Install Workflows consumer scaffolding`) is a verification + LMS-specific configuration pass on top of the template-installed surface. It is not the place to author or modify reusable workflows; those belong upstream in `stranske/Workflows`.

## Verified template-installed surfaces

The following surfaces were verified present and current as of the M0-002 pass. "Current" means the file matches the `stranske/Workflows/templates/consumer-repo/` version unless explicitly noted as a deviation.

### `.github/workflows/`

Synced thin caller workflows (owned upstream in `stranske/Workflows`; fix there, not here):

- `agents-71-codex-belt-dispatcher.yml`
- `agents-72-codex-belt-worker.yml`
- `agents-72-codex-belt-worker-dispatch.yml`
- `agents-73-codex-belt-conveyor.yml`
- `agents-80-pr-event-hub.yml` (consolidated PR event hub; canonical post-`USE_CONSOLIDATED_WORKFLOWS=true`)
- `agents-81-gate-followups.yml` (consolidated gate follow-ups; canonical post-`USE_CONSOLIDATED_WORKFLOWS=true`)
- `agents-auto-label.yml`
- `agents-auto-pilot.yml`
- `agents-autofix-dispatcher.yml`
- `agents-belt-conveyor.yml`, `agents-belt-dispatcher.yml`, `agents-belt-worker.yml` (agent-agnostic belt aliases)
- `agents-capability-check.yml`
- `agents-decompose.yml`
- `agents-dedup.yml`
- `agents-guard.yml`
- `agents-issue-intake.yml`
- `agents-issue-optimizer.yml`
- `agents-keepalive-loop-reporter.yml`
- `agents-orchestrator.yml`
- `agents-pr-health.yml`
- `agents-verifier.yml`
- `agents-verify-to-new-pr.yml`
- `agents-weekly-metrics.yml`
- `autofix.yml`
- `dependabot-automerge.yml`
- `list-llm-models.yml`
- `maint-76-claude-code-review.yml`
- `maint-coverage-guard.yml`
- `reusable-pr-context.yml`

Repo-specific (template provides a starting point with `sync_mode: create_only`, then the repo owns local customization):

- `ci.yml` — repo-specific CI wiring (Python versions, coverage minimum).
- `pr-00-gate.yml` — standard gate, kept aligned to the Workflows default by intent; coverage/Python pins may differ.
- `autofix-versions.env` — repo-specific dependency pins for autofix runs.

Repo-only (not on the Workflows sync manifest):

- `agents-70-orchestrator.yml` — older orchestrator filename retained while migration completes; verify before removing.
- `maint-dependabot-auto-lock.yml` — repo-local dependabot lockfile handling.
- `maint-sync-workflows.yml` — repo-local trigger for opportunistic sync runs (the canonical scheduler is `maint-68-sync-consumer-repos.yml` in `stranske/Workflows`).

### `.github/codex/`

Synced (owned upstream):

- `.github/codex/AGENT_INSTRUCTIONS.md` — base Codex/Claude agent instructions. Repo-local content does NOT modify this file; LMS-specific content layers on via the sibling `PROJECT_CONTEXT.md` so that consumer-sync passes do not have to merge conflicting bodies.
- `.github/codex/prompts/autofix_from_ci_failure.md`
- `.github/codex/prompts/fix_bot_comments.md`
- `.github/codex/prompts/fix_ci_failures.md`
- `.github/codex/prompts/fix_merge_conflicts.md`
- `.github/codex/prompts/keepalive_next_task.md`
- `.github/codex/prompts/verifier_acceptance_check.md`

Repo-only (LMS-specific):

- `.github/codex/PROJECT_CONTEXT.md` — long-form LMS domain context (learner loop, source citation contract, formative LLM policy, ownership table, Phase 1 entities).
- `.github/codex/prompts/lms_project_context.md` — lane-prompt addendum that keepalive, autofix, verifier, fix-bot-comments, fix-ci-failures, and fix-merge-conflicts lanes may include after the synced defaults. The synced prompt files do not reference it directly because they remain upstream-owned.

### `config/`

Template-required (owned upstream, sync-managed):

- `config/coverage-baseline.json` — coverage floor used by `maint-coverage-guard.yml`. Added in the M0-002 diff pass (was absent from the initial template-delivered snapshot; fetched from `stranske/Workflows/templates/consumer-repo/config/coverage-baseline.json`). **Set the `coverage` value to match the project's actual floor before the first coverage-guard run.**
- `config/llm_slots.json` — LLM slot routing table.
- `config/model_registry.json` — model registry for the agent surface.

### `scripts/` and `tools/`

- `scripts/sync_test_dependencies.py` — present (template-installed via the sync manifest).
- `tools/resolve_mypy_pin.py` — present (template-installed via the sync manifest).

### `docs/`

Synced (owned upstream):

- `docs/AGENT_ISSUE_FORMAT.md`
- `docs/LABELS.md`

Repo-only:

- `docs/automation/workflows-consumer-setup.md` (this file).
- `docs/product/*` — research/design content (project plan, early design decisions, research-domain model, development testing surfaces).
- `docs/handoff/`, `docs/research/`, `docs/contracts/` — LMS-specific design and handoff content.

### Repo-root agent files

- `AGENTS.md` — repo agent guide.
- `CLAUDE.md` — Claude-specific consumer-repo context (must stay materially aligned with `AGENTS.md`).
- `README.md`, `WORKFLOW_USER_GUIDE.md`, `DEPENDENCY_TESTING.md` — present.

## Repo configuration

### Repository variables

| Variable                    | Value | Set at                | Purpose |
|-----------------------------|-------|-----------------------|---------|
| `USE_CONSOLIDATED_WORKFLOWS`| `true`| 2026-05-25T04:14:13Z  | Routes PR events through the consolidated `agents-80-pr-event-hub.yml` + `agents-81-gate-followups.yml` hubs. Required by the current consumer default surface in `stranske/Workflows`. |
| `ALLOWED_KEEPALIVE_LOGINS`  | `stranske` | 2026-05-25T04:14:13Z | Restricts keepalive trigger acceptance to a single login during Phase 1 bootstrap. |

Verify with `gh variable list --repo stranske/learning-management-system`.

### Secrets

Secret values are documented in the local-only `Numbers/values.txt` (outside this repository). Required for the current workflow surface:

- `ANTHROPIC_API_KEY` — Claude Code keepalive runner (`agent:claude` PRs).
- `OPENAI_API_KEY` and/or `CODEX_AUTH_JSON` — Codex keepalive runner (`agent:codex` PRs). Register whichever the agent-registry entry for Codex expects.
- `LANGSMITH_API_KEY` — LangSmith tracing surface; tracing is opt-in per-PR via labels.
- A service-bot PAT for cross-repo automation when required by reusable callers in `stranske/Workflows`.

Never paste secret values into PR bodies, issue bodies, prompt files, or instruction files. Reference them as `${{ secrets.<NAME> }}` only inside `.github/workflows/` files, and only when modifying those files is permitted by the synced security boundaries.

## Deviations from the template default

| File                                | Deviation | Why | Conflict risk on next sync |
|-------------------------------------|-----------|-----|----------------------------|
| `.github/codex/AGENT_INSTRUCTIONS.md` | LMS-domain append section added after the base synced content. | Acceptance criterion for issue #2 requires this file to contain LMS-domain context. The append adds the four key LMS policies (learner-loop integrity, source citations, formative-only LLM, ownership scope) and a pointer to `PROJECT_CONTEXT.md`. The HTML comment marker `<!-- LMS-DOMAIN-APPEND -->` identifies the append boundary so a sync pass can detect drift. | Low. A consumer-sync overwrite replaces the base content but should not drop lines after the marker unless the upstream template grows past the original footer line. Re-apply this section from `PROJECT_CONTEXT.md` if a sync pass drops it. |
| `.github/codex/PROJECT_CONTEXT.md`  | New file, not on the sync manifest. | Holds LMS-specific long-form domain context for lane prompts to reference. Lives next to the synced `AGENT_INSTRUCTIONS.md` so an agent that reads the base instructions discovers the LMS-domain layer in the same directory. | None. |
| `.github/codex/prompts/lms_project_context.md` | New file, not on the sync manifest. | LMS-aware lane prompt that complements the synced defaults. | None. |
| `.github/workflows/agents-70-orchestrator.yml` | Present in repo, not in current template. | Older orchestrator retained pending migration to `agents-80-pr-event-hub.yml` consolidated routing. | None. The sync run will not remove unmanaged files. |
| `.github/workflows/maint-dependabot-auto-lock.yml` | Present in repo, not in current template. | Repo-local dependabot lockfile handling. | None. |
| `.github/workflows/maint-sync-workflows.yml` | Present in repo, not in current template. | Repo-local opportunistic sync trigger. The canonical scheduler is upstream in `Workflows`. | None. |
| `.github/workflows/pr-00-gate.yml`  | Differs from template body. | Sync mode is `create_only`; coverage/Python pins and lint surface are intentionally repo-specific. | None by sync mode. Keep the standard gate shape unless a documented exception is added. |
| `.github/workflows/ci.yml`, `.github/workflows/autofix-versions.env` | Differs from template. | Repo-specific CI wiring; both are `create_only` in the sync manifest. | None by sync mode. |

If a deviation is later reverted upstream (for example, if the LMS-style addendum pattern becomes a first-class sync surface), update this table and the affected files together.

## `gh issue create` acceptance check

The 25 priority:high + 6 priority:normal LMS issues (numbered #1-#31 in this repository) were materialized via `gh issue create` against the AGENT_ISSUE_FORMAT body shape defined in `docs/AGENT_ISSUE_FORMAT.md`. They were accepted without errors, carry the expected `priority:*` + `repo-review-approved` labels, and are visible to the opener-lane discovery search. This implicitly verifies the M0-002 acceptance criterion that `gh issue create` against this repo accepts AGENT_ISSUE_FORMAT bodies.

For a future explicit dry-run, the equivalent command shape is:

```sh
gh issue create \
  --repo stranske/learning-management-system \
  --title "<title>" \
  --body-file <path-to-AGENT_ISSUE_FORMAT-body> \
  --label "priority:normal" --label "repo-review-approved"
```

The body file should follow `docs/AGENT_ISSUE_FORMAT.md` exactly (Why / Scope / Non-Goals / Tasks / Acceptance Criteria / Implementation Notes sections).

## Maintenance

- Treat the synced surfaces as upstream-owned. When something needs to change there, fix it in `stranske/Workflows` and let the consumer-sync workflow propagate the change.
- Refresh this document whenever a deviation is added, removed, or moved between owners.
- If an agent or contributor needs LMS-specific guidance to change, prefer editing `.github/codex/PROJECT_CONTEXT.md` and `.github/codex/prompts/lms_project_context.md` (both repo-local, not synced); do not modify `.github/codex/AGENT_INSTRUCTIONS.md` or any other file owned upstream.
