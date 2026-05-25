# 0001 — Backend Stack and Phase 1 Product Boundary

**Status:** Accepted
**Date:** 2026-05-25
**Supersedes:** none

## Decision

Use **Python + FastAPI + SQLAlchemy + Alembic + Pydantic + pytest + Postgres + REST/OpenAPI** as the v1 backend stack, with **Jupyter and pandas** included for empirical mastery-rule tuning and LLM-quality analysis. Bound Phase 1 scope (Milestones 0-4) to the 11-entity Minimum Core listed below; explicitly defer the higher-scope entities until Milestone 5 or later.

## Context

The Learning Management System project is a public-but-personal v1 learning engine: API-first, evidence-driven, formative-LLM-mediated, with the project owner as the first user. The design corpus converged through two rounds of parallel-agent design review across two source documents:

- **[`docs/product/project-plan.md`](../../product/project-plan.md) — Milestone 0: Repo And Decision Foundation** establishes that the repo needs a written stack decision and initial backlog before implementation begins, with acceptance criteria tied to learning-science intent.
- **[`docs/product/early-design-decisions.md`](../../product/early-design-decisions.md) — Segment 1: First Product Boundary** selected a local/private personal-research-note slice as the first concrete content path, with the project owner as the first real user, keeping the core learning loop broad enough for other use cases.
- **[`docs/product/early-design-decisions.md`](../../product/early-design-decisions.md) — Segment 7: Stack, Governance, And Implementation** selected Python + FastAPI + Postgres + REST/OpenAPI + local auth + Workflows consumer setup as the working technical defaults.

Implementation begins from a Workflows consumer-template scaffolding installed via the `stranske/Template` GitHub template-repository mechanism.

Before any module-level code lands, the repo needs a written commitment on the stack and on what Phase 1 includes vs. defers, so issue-driven implementation work doesn't drift back toward older, broader scope.

## Options Considered

- **Python + FastAPI vs. TypeScript-first backend.** TypeScript would have aligned with potential PWA frontends but would have fragmented from `stranske/Workflows`'s Python-first reusable CI and from the LangChain/LangGraph/LangSmith integration target. Python wins on alignment.
- **Postgres vs. SQLite for v1.** SQLite is simpler locally but doesn't represent production semantics (constraints, JSONB, RLS path). Postgres-first keeps the data model honest from day one.
- **REST/OpenAPI vs. GraphQL vs. typed RPC.** REST keeps contracts stable, testable, and agent-friendly; GraphQL adds resolver/auth/caching complexity prematurely; typed RPC fits TypeScript stacks better. REST wins.
- **Full curriculum scope (Course/Module/Lesson) vs. trimmed personal-learning slice.** Carrying curriculum authoring through Phase 1 inflates schema and surface area beyond what the Minimum Demo needs. Trimming wins; curriculum lands in Milestone 5+.

## Selected Direction

**Stack (v1):**

- **Backend:** Python 3.12 / 3.13, FastAPI, SQLAlchemy 2.x, Alembic, Pydantic v2, pytest.
- **Persistence:** Postgres first.
- **API style:** REST + OpenAPI.
- **Auth:** local auth placeholder; SSO-ready identity model.
- **LLM stack:** LangChain / LangGraph + LangSmith, with a thin in-house `LLMClient` wrapper enforcing budget / routing / trace classification / redaction / structured-output validation (see `docs/product/project-plan.md` LLM Operational Requirements).
- **Analysis tooling:** Jupyter + pandas included from day one for empirical mastery tuning at Milestone 6-7.
- **Lint/format/type/test:** Ruff + Black + mypy + pytest, exercised via the consumer template's `ci.yml` thin caller.

**Phase 1 Minimum Core (11 entities):**

| Entity | Note |
| --- | --- |
| `User` | local auth placeholder; SSO-ready model |
| `Learner` | linked to User; carries scope-aware queries |
| `KnowledgeNode` | carries `ownership_scope` (`personal` / `institutional`) |
| `KnowledgeEdge` | prerequisite edge type only in v1; carries `ownership_scope`; DB CHECK forbids cross-scope without an explicit `GraphReference` |
| `SourceReference` | first-class entity with stable identity, `content_hash`, drift status |
| `Prompt` | links to ≥1 `SourceReference`; carries provenance (`authoring_method`, `authoring_actor`, `reviewing_actor`, `approval_timestamp`, `llm_model`, `prompt_template_version`) |
| `Attempt` | structured feedback as a field (no separate `FeedbackRecord` table in v1) |
| `EvidenceRecord` | verbose schema (timestamp, demand level, scorer identity, scoring method, raw/normalized/max score, partial credit, item difficulty placeholder, attempt context, validity scope, answer artifact ref, etc.) |
| `ReviewQueueItem` | reason codes, daily cap, pause/vacation mode, stale states |
| `LearningGoal` | knowledge-type-tagged; absorbs the v1 role of the deferred `LearningObjective` |
| `LLMSession` | carries `trace_class` (`evidence-grade` / `formative` / `ephemeral`) |

`MasteryEstimate` is a **computed view** over `EvidenceRecord`, not a separately-written table.

## Deferred (Phase 2+ / Milestone 5 or later)

| Deferred | Lands in |
| --- | --- |
| `Course`, `Module`, `Lesson` (curriculum authoring entities) | Milestone 5+ when institutional curriculum authoring enters |
| `LearningObjective` as a separate entity | Milestone 5+ (folded into `LearningGoal` for v1) |
| `FeedbackRecord` as a separate table | Promoted from `Attempt` field when feedback templates or rubrics need it |
| `LearningPrinciple` / `LearningClaim` / `EvidenceSource` runtime tables | Stay as YAML in `docs/research/registry/` with a build-time validator; runtime tables only if a product feature reads them |
| `InteractionMode`, `LLMInteractionPolicy` runtime tables | Stay as code/config in v1; runtime tables when authoring or governance needs them as data |
| `CapabilityTarget`, `CapabilityEstimate`, `GapAnalysis`, `MaintenancePlan` | **Milestone 5** (personal gap-closing artifacts) |
| `CertificationSnapshot`, `RecertificationPolicy`, `EvidenceDecayPolicy` | Deferred indefinitely until institutional or evaluation scope enters |
| `/capability/*`, `/curriculum/*`, `/research/*` API endpoints | Phase 2+ block in the API Surface Sketch |
| Runtime research-registry CRUD APIs | Deferred indefinitely |

## Reasoning

- **Stack alignment.** Python + FastAPI matches `stranske/Workflows`'s reusable-CI Python pipeline, LangChain/LangSmith integration, and the existing consumer-repo fleet's conventions. No friction with the shared automation surface.
- **Postgres + Alembic** from day one prevents schema lessons that SQLite hides (foreign-key behavior, JSONB ergonomics, eventual RLS).
- **REST + OpenAPI** gives agents (and the keepalive runner) stable, introspectable contracts to act on. GraphQL would add resolver/auth complexity well before it would pay off; typed RPC fits the wrong language ecosystem.
- **Phase 1 trim.** The Minimum Demo Criterion at end of Milestone 4 (8-item pre-registered day-30 retention test) is the v1 thesis-validation gate. Any entity not on the critical path to that demo is scope creep at this stage. Curriculum and certification are intellectually central but operationally premature.
- **`EvidenceRecord` as the load-bearing schema decision.** The mastery rule (FSRS-4.5 placeholder) is explicitly throwaway scaffolding. Schema generality (uniform `EvidenceRecord` with every signal a future learned model could want) matters more than getting the rule right today.

## Risks

- **Postgres setup weight for local-first development.** Mitigated by documenting a slim `docker compose` or `brew services postgresql@16` path in Milestone 1 backend-setup docs.
- **REST contract churn before the model stabilizes.** Mitigated by treating the v1 API surface as documented but malleable; OpenAPI keeps the contract introspectable.
- **Trimmed Phase 1 may force retrofitting if early demo work reveals a missing entity.** Mitigated by keeping the verbose `EvidenceRecord` schema, ownership-scope enforcement, and prompt provenance — the structural pieces that are hardest to retrofit.

## Follow-up Questions

- What exact local Postgres setup do we standardize on (Homebrew service vs. dockerized) for the project owner's machine?
- Which Workflows consumer-template files (if any) need project-specific customization beyond `.github/codex/` content (issue M0-002 addresses this)?
- At what point in Milestone 6-7 does empirical mastery-rule tuning produce a `MasteryModelV2` that should replace the FSRS-4.5 placeholder?

## Review Date

After Milestone 4 ends and the Minimum Demo Criterion is run, revisit this record. Decision points: (a) whether the Phase 1 trim held up, (b) whether any deferred entity needs to be promoted earlier, (c) whether stack choices remain right for Milestones 5-8.

