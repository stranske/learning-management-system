# LMS Project Context (lane-prompt reference)

> Repo-local file. Not on the consumer-sync manifest. Lane prompts can include this for LMS-specific framing without modifying the synced base [`AGENT_INSTRUCTIONS.md`](AGENT_INSTRUCTIONS.md) or the synced [`prompts/`](prompts/) files.

## Read Order

For any non-trivial implementation task in this repo, the operating agent should read these in order before changing code:

1. The synced base `.github/codex/AGENT_INSTRUCTIONS.md` (security boundaries; do not modify locally).
2. This file (long-form domain context).
3. `docs/product/project-plan.md` and `docs/product/early-design-decisions.md` for the canonical product/segment decisions.
4. `docs/product/research-domain-model.md` for the Phase 1 Minimum Core entity definitions.
5. `docs/product/development-testing-surfaces.md` for the testing surfaces and the Inspect/Learn/Review boundary.

## The Learner Loop

The system implements one core loop and the supporting surfaces around it:

```
goal -> prompt -> learner attempt -> evidence -> formative feedback -> mastery update -> next action (scheduled review or new prompt)
```

When writing code that touches any stage:

- Preserve the evidence trail. Every `Attempt` must produce an `EvidenceRecord`, and every `EvidenceRecord` must be traceable to a `Prompt`, `LearningGoal`, and one or more `KnowledgeNode`s.
- Update `MasteryEstimate` from evidence, never from LLM judgement.
- Schedule the next action through `ReviewQueueItem` rather than ad hoc timers; the FSRS adapter (issue #22) owns spaced-repetition math.

## Source Citation Contract

Every research-derived LLM output must reference one or more `SourceReference` records. The `SourceReference` CRUD + drift-scan surface (issue #11) is load-bearing for the rest of the system. Treat:

- A missing citation on a research-grounded prompt or answer as a correctness defect.
- A `SourceReference` whose snapshot drifts from the live upstream as a tracked event to surface, not silently update.
- Importer output (issue #13 Markdown, issue #14 CSV) as the supply chain for `SourceReference`. Importer errors block downstream `LearningGoal` publication.

## Formative LLM Policy

LLM behavior in this repo is bounded:

- LLM produces drafts, hints, explanations, and structured prompts.
- LLM does NOT decide mastery. `MasteryEstimate` reads `EvidenceRecord` rows and computes mastery numerically.
- LLM responses that influence learner-visible content go through `LLMSession` (issue #25) for logging, replay, and the gold-set eval harness (issue #26).
- Daily cap, pause mode, and stale-handling (issue #24) are enforceable budgets, not advisory limits.

## Ownership And Sync Boundaries

| Path                                             | Owner                  | Notes |
|--------------------------------------------------|------------------------|-------|
| `src/`, `tests/`, `docs/product/`                | This repo              | Application + research/design content. |
| `docs/automation/workflows-consumer-setup.md`    | This repo              | Per-repo automation documentation. |
| `.github/codex/PROJECT_CONTEXT.md` (this file)   | This repo              | Repo-local lane-prompt reference. |
| `.github/codex/AGENT_INSTRUCTIONS.md`            | `stranske/Workflows`   | Synced base instructions. Fix upstream; do not modify locally. |
| `.github/codex/prompts/*.md` except `lms_*.md`   | `stranske/Workflows`   | Synced base prompts. Fix upstream. |
| `.github/codex/prompts/lms_*.md`                 | This repo              | Repo-local lane addenda. |
| `.github/workflows/agents-*.yml`                 | `stranske/Workflows`   | Reusable workflow thin callers. Fix upstream. |
| `.github/workflows/autofix.yml`                  | `stranske/Workflows`   | Synced. Fix upstream. |
| `.github/workflows/ci.yml`, `pr-00-gate.yml`     | This repo (create-only)| Repo-specific coverage/python pins. |
| `.github/workflows/autofix-versions.env`         | This repo              | Repo-specific dependency pins. |

## Phase 1 Minimum Core Entities

- `User` / `Learner` (placeholder auth)
- `LearningGoal`
- `KnowledgeNode` / `KnowledgeEdge`
- `SourceReference`
- `Prompt`
- `Attempt`
- `EvidenceRecord`
- `MasteryEstimate`
- `ReviewQueueItem`
- `LLMSession`

`CapabilityTarget`, `CapabilityEstimate`, `GapAnalysis`, and `MaintenancePlan` are Milestone 5+ and out of scope for M0-M4 issues.

## Excluded From Phase 1

- Multi-tenant institutional deployment (Phase 2+).
- Public/client education flows (lower-priority pilot).
- Dyslexia-aware accessibility design spike (deferred).
- Capability scoring + gap analysis (`/capability/*` API block, Milestone 5).

## Key Repos To Cross-Reference

- `stranske/Workflows` — source of truth for `.github/workflows/`, the synced base `.github/codex/` content, and `templates/consumer-repo/`.
- `stranske/Template` — base GitHub template repo this repo was cloned from.

## Secrets Registration Plan

Secrets required by the workflows are documented in the local-only `Numbers/values.txt` outside this repo. Register at least:

- `ANTHROPIC_API_KEY` (Claude Code keepalive runner)
- `OPENAI_API_KEY` / `CODEX_AUTH_JSON` (Codex keepalive runner; whichever the registry's Codex entry expects)
- `LANGSMITH_API_KEY` (LangSmith tracing surface; tracing is opt-in per-PR via labels)
- A service-bot PAT for cross-repo automation when required by `stranske/Workflows` reusable callers

Never paste secret values into this repository, into PR descriptions, or into prompt/instruction files. Reference them as `${{ secrets.<NAME> }}` only inside `.github/workflows/` files, and only when modifying those files is permitted by the synced security boundaries.
