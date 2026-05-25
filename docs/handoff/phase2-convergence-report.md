# Phase 2 Convergence Report — Initial Issue Queue

Status: Codex Phase 2 issue generation complete (`docs/handoff/phase2-codex-issue-candidates.json`); Claude review below for project owner adjudication before filing.

## Summary

**31 issues generated across Milestones 0-4** (M0: 4 | M1: 4 | M2: 6 | M3: 7 | M4: 10).

**Structural validation (all pass):**

- JSON parses; 31 issues with 31 unique `issue_id` values.
- 0 unresolved `depends_on` references.
- DAG has no cycles.
- All issues carry `priority:*` + `repo-review-approved` + `milestone:M*` labels.
- All 11 Phase 1 Minimum Core entities are covered (`User`, `Learner`, `KnowledgeNode`, `KnowledgeEdge`, `SourceReference`, `Prompt`, `Attempt`, `EvidenceRecord`, `ReviewQueueItem`, `LearningGoal`, `LLMSession`).
- All 6 Minimum Demo Criterion requirements traceable to issues (import 10 notes → M2-005; 30 prompts → M3-002 + M4-009; attempts + confidence → M3-003; verbose EvidenceRecord → M3-004; Inspect mastery + review queue → M3-006 + M4-002; study-coach session → M4-006 + M4-008; day-30 retention protocol → M4-010).
- AGENT_ISSUE_FORMAT bodies look well-formed (Why / Scope / Non-Goals / Tasks / Acceptance Criteria / Implementation Notes; tasks start with verbs; criteria have verifiable test names).

**Codex's overall assessment:** *"This queue is ready to file once the repo exists and the Workflows consumer template is installed. The main residual dependency is operational rather than architectural: real provider credentials, LangSmith retention settings, and the actual project-owner research-note slice must be supplied when the M4 demo is run."*

**Claude's overall assessment:** Agree on substance. The queue is ~80-90% ready to file as-is. Five items below benefit from your adjudication before filing — three are framing/scope corrections that catch where Codex made reasonable assumptions that don't match other decisions in our docs, one is an external-to-repo task we shouldn't lose track of, and one is a small inconsistency in `--apply` vs `--dry-run` scope.

## Items for adjudication

### A. M0-002 — Workflows consumer scaffolding: reframe from "copy template" to "verify pre-installed"

**Codex's framing:** "Copy or apply the consumer-repo setup from `Workflows/templates/consumer-repo` into this repo where appropriate."

**Issue:** We agreed earlier to create the new repo via `gh repo create stranske/learning-management-system --template stranske/Template --public`. That mechanism uses GitHub's template-repository feature, which means the consumer-template files arrive **pre-installed** in the new repo at creation time. The `maint-68-sync-consumer-repos.yml` automation then keeps them current. M0-002 as written suggests we're doing the install ourselves, which would duplicate effort and risk drift.

**Recommended action:** Rewrite M0-002 to be a verification + project-specific-customization issue:
- Verify the template-installed `.github/workflows/`, `AGENTS.md`, `CLAUDE.md`, `docs/AGENT_ISSUE_FORMAT.md`, `docs/LABELS.md`, `scripts/sync_test_dependencies.py`, `tools/resolve_mypy_pin.py` are present and current.
- Set `USE_CONSOLIDATED_WORKFLOWS=true` as a repo variable (agreed earlier).
- Add project-specific `.github/codex/AGENT_INSTRUCTIONS.md` and `.github/codex/prompts/` content for the LMS domain.
- Add `docs/automation/workflows-consumer-setup.md` documenting which template files are in use and any project-specific deviations.
- Document the secret registration plan (using `Numbers/values.txt` per earlier conversation).

**Owner input needed:** Yes — confirm reframing, or push back if you want the "copy template" pattern instead.

### B. M0-003 — Architecture docs: link to existing project-plan.md rather than duplicate content

**Codex's plan:** Create four new architecture docs (`docs/architecture/api-v1.md`, `data-model-v1.md`, `source-citation-and-provenance.md`, `privacy-trace-classification.md`) that re-describe content already in `docs/product/project-plan.md` and `docs/product/early-design-decisions.md`.

**Issue:** This duplicates ~30-50% of project-plan.md content. Single-source-of-truth would prevent drift; we already added Segment 9 strengthening, ownership-boundary enforcement, source-citation policy, prompt provenance, FSRS adapter rule table, etc. to project-plan.md and don't want them to drift across files.

**Recommended action:** Reduce M0-003 scope to:
- Create `docs/architecture/README.md` as an index that points to the relevant sections of `docs/product/project-plan.md` and `docs/product/early-design-decisions.md` (with stable anchors).
- Add `docs/architecture/decision-records/` directory + `0001-backend-stack-and-boundary.md` (already in M0-001 scope, so adjust to avoid overlap with M0-001).
- Skip the four duplicate per-topic docs. If a domain area later needs its own architecture doc (e.g., once authoring-assist matures), create it then.

**Owner input needed:** Yes — confirm "link don't duplicate," or push back if you'd rather have separate architecture docs.

### C. M1-003 — CI workflow already comes from the consumer template

**Codex's framing:** "Add CI workflow for lint, format check, type check, and tests."

**Issue:** The consumer template's `ci.yml` is a thin caller for `stranske/Workflows/.github/workflows/reusable-10-ci-python.yml@main` (or `@v1`) which already runs Ruff, Black, mypy, and pytest on Python 3.12 and 3.13. The CI workflow file itself arrives via the template; M1-003 should configure `pyproject.toml` for the tools the template invokes, not author a new CI workflow file.

**Recommended action:** Rewrite M1-003 scope to:
- Configure `pyproject.toml` `[tool.ruff]`, `[tool.black]`, `[tool.mypy]`, `[tool.pytest.ini_options]` so the template-provided CI runs cleanly on this codebase.
- Add `Makefile` or `justfile` aliases for local checks.
- Verify the template's `ci.yml` runs against this repo's tooling.
- **Do not** author `.github/workflows/ci.yml` from scratch.

**Owner input needed:** Yes — confirm "configure tools, don't author workflow," or push back.

### D. M3-007 — Export contract should include `--apply`, not just `--dry-run`

**Codex's note:** *"If `--apply` is not implemented here, leave a focused follow-up issue; dry-run verification is required now."*

**Issue:** `docs/product/project-plan.md` "Export and import contract (v1)" says: *"`lms import --dry-run <file>` validates schema, FK integrity, and ID collision checks without writing. `lms import --apply <file>` writes if `--dry-run` passes. **Both ship in v1.**"* Codex's M3-007 partially deviates from this by treating `--apply` as optional.

**Recommended action:** Expand M3-007 tasks and acceptance criteria to include `lms import --apply`. The marginal work over dry-run is small (the validation logic is shared) and it's load-bearing for the export contract being a real backup story.

**Owner input needed:** No — proceeding with expansion unless you push back.

### E. External Workflows registry updates — separate Workflows-repo PR, not in this queue

**Not in queue (correctly).** When the new repo is created, these locations need an atomic update in a single Workflows-repo PR:

- `Workflows/.github/workflows/maint-68-sync-consumer-repos.yml` — `REGISTERED_CONSUMER_REPOS` env var.
- `Workflows/config/repo_review_registry.json` — new entry with `local_path: learning-management-system`, `status: active`, `cadence: weekly`, decision_anchor for the learning-engine thesis.
- `Workflows/config/repo_review_profiles.json` — new profile (progress_summary, readiness_summary, review_focus, concerns).
- `Workflows/config/source_of_truth_docs.yml` — docs to monitor for drift (`README.md`, `AGENTS.md`, `docs/product/project-plan.md`, `docs/product/early-design-decisions.md`).
- `Workflows/README.md` — first-party consumers list.

And locally:

- `~/.codex/handoff/prompts/claude-opener.md` — supported-repos list.
- `~/.codex/handoff/prompts/claude-closer.md` — supported-repos list.
- (Codex equivalent prompts if separate.)
- `/Users/teacher/Library/CloudStorage/Dropbox/Learning/Code/CLAUDE.md` — "Supported repos (the lane fleet)" list.

And external (out of my reach):

- `stranske/Workflows-Integration-Tests` — separate repo; needs its own parallel PR adding LMS to its fixtures.

**Recommended action:** Track this as a Phase 3 task (post-Phase-2-adjudication, before-or-just-after repo creation). I'll draft the registry-update PR for Workflows after you approve the issue queue.

**Owner input needed:** No, just visibility — this won't be forgotten.

## Smaller observations (not blocking; flagging for awareness)

- **`docs/research/registry/`** vs `docs/research/` for the YAML files (M2-001): Codex used a `registry/` subdirectory. Our research-domain-model.md note says "under `docs/research/`." Subdir is fine and probably cleaner (separates registry from chapter summaries); I'd accept Codex's choice and note it in the doc. No action needed unless you object.
- **`source_visibility` body export semantics** (M3-007 + M2-003): the export contract says "local-only source bodies excluded by default." Source *bodies* (the actual passage text) aren't stored in `SourceReference` itself — the schema only stores the locator and hash. The "body" is fetched on demand from the locator. So exporting "the body" really means "the resolved content at the locator" — worth verifying M3-007's implementation handles this distinction.
- **M4-009 authoring-assist priority normal vs high**: I'd be tempted to bump M4-009 to `priority:high` since the Minimum Demo target of "~30 retrieval prompts" probably can't be hit by hand at M4 launch time. But it's defensible at `priority:normal` if the demo plan is to hand-author all 30. Your call when you adjudicate.
- **M0-001 backend stack decision record vs M0-003 architecture decision records**: M0-001 creates `docs/architecture/decision-records/0001-backend-stack-and-boundary.md`; M0-003 creates the `docs/architecture/` directory and README. Minor sequencing question — does M0-003 depend on M0-001 (it does in Codex's graph) or vice versa? Codex's depends_on is correct; nothing to adjudicate.

## What I'd like from you

1. **Items A, B, C** — confirm reframings, or push back?
2. **Item D** — silent default is expand M3-007 to include `--apply`; OK?
3. **Items E and smaller observations** — visibility only, no action needed unless you spot something amiss.
4. **Anything Codex missed** that you want surfaced before filing?

Once you've adjudicated, I'll:

1. Apply the edits to the queue JSON (rewrite M0-002, M0-003, M1-003 bodies; expand M3-007 to include `--apply`).
2. Optionally re-spawn a Codex round-2 verification on the fixes (consistent with the Phase 1 pattern), or skip directly to filing prep.
3. Begin Phase 3 — repo creation, registry updates, secret registration from `Numbers/values.txt`, then `upload_repo_review_issues.py --apply` (or its equivalent) against the final queue.

The full issue queue is at `docs/handoff/phase2-codex-issue-candidates.json` (~68KB; 31 issue objects with full AGENT_ISSUE_FORMAT bodies).
