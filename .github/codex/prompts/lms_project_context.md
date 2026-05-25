# LMS lane-prompt addendum: project context

> Repo-local prompt. Not on the consumer-sync manifest. Lane prompts in this repo (keepalive, autofix, verifier, fix-bot-comments, fix-ci-failures, fix-merge-conflicts) may include this file by reference to layer LMS-specific framing on top of the synced defaults in this same directory. Do NOT modify the synced prompt files; add LMS-specific lane variants here as `lms_*.md` instead.

## Always carry into any lane

Before changing code in this repository, the operating agent should treat the following as preconditions on the task:

1. **Read order:** the synced `.github/codex/AGENT_INSTRUCTIONS.md` (security boundaries), then `.github/codex/PROJECT_CONTEXT.md` (LMS domain layer), then `docs/product/early-design-decisions.md` Segments 1 and 7, then the issue body, then the touched code.
2. **Learner loop integrity:** never bypass the chain `Prompt -> Attempt -> EvidenceRecord -> MasteryEstimate -> ReviewQueueItem`. If a change would let LLM output skip evidence or short-circuit mastery computation, stop and add `needs-human`.
3. **Source citations are load-bearing:** any LLM-touching code path that produces learner-visible output must carry a `SourceReference` linkage. Missing or stub citations are a correctness defect, not a stylistic detail.
4. **Formative-only LLM:** LLM responses inform; `MasteryEstimate` decides. Code review surfaces that mix the two should be split or rejected.
5. **Ownership sanity:** if a change would edit a file the consumer-sync manifest owns (`.github/workflows/agents-*.yml`, synced `.github/codex/prompts/*.md`, `AGENT_INSTRUCTIONS.md`, synced scripts/docs), stop and route the change to `stranske/Workflows` instead. LMS-specific lane content belongs in this file or in `PROJECT_CONTEXT.md`, never inside a synced file.

## Lane-specific notes

- **Keepalive next-task lane.** Tasks may reference Milestone 1-4 issues (M0 is foundational, M5+ is out of scope). Prefer the smallest evidence-producing slice that the issue's acceptance criteria require; defer optional polish.
- **Fix-CI-failures lane.** The repo uses `pr-00-gate.yml` (repo-local, `create_only` synced from template) and `ci.yml` (repo-local). Coverage minimums and Python versions are intentionally repo-specific. Do not regress them to template defaults during a CI fix.
- **Autofix lane.** Lint/format autofix should never touch `docs/product/*.md` content or `docs/architecture/decision-records/*.md` content. Those are research/design artifacts where wording is load-bearing.
- **Fix-bot-comments lane.** Treat Copilot/review-bot comments about LLM behaviour, citation contracts, or mastery calculation as design-level — surface them rather than rewriting silently. Mechanical lint/style review comments may be addressed directly.
- **Verifier-acceptance lane.** Acceptance criteria for LMS issues frequently include "produces an evidence record" or "writes to `MasteryEstimate`" rather than only "tests pass". Verify those domain invariants, not only the test suite green-state.
- **Fix-merge-conflicts lane.** Conflict resolution that touches synced files (per the ownership table in `PROJECT_CONTEXT.md`) should prefer the upstream `stranske/Workflows` content; conflicts in repo-local files should prefer the in-flight change.

## When to stop and ask

- The fix requires editing `AGENT_INSTRUCTIONS.md`, any synced file in `.github/codex/prompts/`, or any file declared in the `stranske/Workflows` sync manifest.
- The fix asks the LLM to act as a final authority on whether the learner mastered a concept.
- The fix would silently update or fabricate a `SourceReference` snapshot instead of surfacing drift.
- The fix would create Phase-2+ entities (`CapabilityTarget`, `CapabilityEstimate`, `GapAnalysis`, `MaintenancePlan`) for an M0-M4 issue.

Add the `needs-human` label and document the question instead of guessing.
