# Project Documentation Index

Status: current informational map for local review.

This repository is currently a documentation-first LMS design project. It is not yet an initialized Git repository and does not yet contain implementation code. The docs are organized into research artifacts and product/design artifacts.

## Start Here

1. [Project Review Brief](project-review-brief.md)
2. [Product Project Plan](product/project-plan.md)
3. [Early Design Decisions](product/early-design-decisions.md)
4. [Development Testing Surfaces](product/development-testing-surfaces.md)
5. [Learning Principles Register](research/learning-principles.md)

## Product And Design Docs

| File | Purpose |
| --- | --- |
| [product/project-plan.md](product/project-plan.md) | Main product architecture and roadmap. Covers design thesis, audiences, modules, workflows, API sketch, data priorities, milestones, backlog, and open questions. |
| [product/early-design-decisions.md](product/early-design-decisions.md) | Segmented decision queue with working decisions for product boundary, mastery/current capability, LLM interaction, graphs, certification, public/accessibility, and stack/governance. |
| [product/development-testing-surfaces.md](product/development-testing-surfaces.md) | Lightweight UI/testing surfaces needed during development: learner loop, LLM study, authoring, graph, evidence inspector, scheduler, capability, dashboard, public education, research review, and accessibility/reading stress test. |
| [product/research-domain-model.md](product/research-domain-model.md) | Research-to-product conceptual schema for principles, claims, evidence, interventions, outcomes, and experiments. |

## Research Docs

| File or folder | Purpose |
| --- | --- |
| [research/learning-principles.md](research/learning-principles.md) | Main register translating learning research into LMS design commitments. |
| [research/references.md](research/references.md) | Reusable bibliography and claim-support notes. |
| [research/kindle-source-notes.md](research/kindle-source-notes.md) | Notes on Kindle extraction limits and provenance. |
| [research/math-academy-way-outline.md](research/math-academy-way-outline.md) | Index for Math Academy outline work. |
| [research/math-academy-way/README.md](research/math-academy-way/README.md) | Detailed Math Academy worklog and chapter inventory. |
| [research/math-academy-way/synthesis-with-how-do-we-learn.md](research/math-academy-way/synthesis-with-how-do-we-learn.md) | Comparative synthesis between *The Math Academy Way* and *How Do We Learn?*. |
| [research/chapter-01-scientific-study-summary.md](research/chapter-01-scientific-study-summary.md) and section summaries | Section-by-section summaries of *How Do We Learn?* and related design implications. |

## Current Design Decisions

Original first-pass decisions:

- First prototype: local/primitive, with the project owner as first user.
- First content path: personal learning from collected research notes, while keeping the architecture broad.
- Backend: Python, FastAPI, SQLAlchemy, Alembic, Pydantic, pytest.
- Database: Postgres first.
- API: REST plus OpenAPI first.
- Auth: local auth first, SSO-ready identity model.
- Process: use the local Workflows repo as the consumer automation source once this project becomes a GitHub-backed repo.
- LLM: LangChain/LangGraph and LangSmith are core architecture elements.
- Knowledge graph: support personal and institutional graphs; implement personal/research-note graph first.
- Public education: later public-facing pilot with low-stakes checks and aggregate misconception reporting.
- Accessibility: dyslexic reading is a design stress test, with motivation/reward, phonological awareness, decoding fluency, reading-comprehension assessment, and working-memory/cognitive-load concerns made explicit.

Second-review-pass refinements:

- Repository: `learning-management-system`, public visibility, created from the `stranske/Template` GitHub template (or SETUP_CHECKLIST.md equivalent) so consumer-template workflows arrive pre-installed. Research-note content (chapter/section summaries, Math Academy outline and synthesis, Kindle-derived highlights) stays in a separate local folder and is **not** committed to the public repo. Reversible decision.
- Mastery rule: ship v1 with FSRS-4.5 placeholder; `MasteryEstimate` is a computed view over `EvidenceRecord`; the verbose `EvidenceRecord` schema is the load-bearing decision; empirical tuning planned for Milestone 6-7 once ~500-1000 evidence records exist on overlapping nodes.
- Phase 1 entities trimmed to the minimum that proves the learner loop; `LearningPrinciple` / `LearningClaim` / `EvidenceSource` live in `docs/research/` as YAML rather than runtime DB tables; `Course` / `Module` / `Lesson` deferred until institutional curriculum authoring enters.
- Source citation: every prompt links to a `SourceReference` with a `content_hash`; source shown after the attempt; LLM feedback constrained to cite the linked set; uncited LLM claims flagged `unverified`.
- Prompt provenance: every prompt records `authoring_method`, `authoring_actor`, `reviewing_actor`, `approval_timestamp`, and (for LLM-authored) `llm_model` and `prompt_template_version`; audit log on authoring actions.
- LLM routing: single client wrapper; per-mode model config; daily cost log line per mode; budget kill-switch from v1; eval gold set (10-30 transcripts) built before the first `study-coach` flow.
- LLM privacy: trace classification (`evidence-grade` / `formative` / `ephemeral`) with class-driven retention; default Anthropic API with no training opt-in; PII redaction on write; learner keep/forget controls.
- Personal-learning sustainability: pause/vacation mode, daily cap, stale-item handling shipped in v1; cadence-tuning decision deferred until ~30 days of real use (Milestone 4-5).
- Personal/institutional boundary: `ownership_scope` enforced at the schema level on `KnowledgeGraph` / `KnowledgeNode` / `KnowledgeEdge`; cross-scope links explicit, never edge merges; separate deployments preferred over multi-tenant rows when firm content enters scope.
- Mobile: mobile-friendly default on every UI surface; PWA on the roadmap.
- Inspect surface: shipped in Milestone 3, not at the end.
- Backup/export contract: shipped in v1.
- Analysis tooling: Jupyter and pandas included in the project from the start.
- Certification: personal gap-closing artifacts (`CapabilityTarget`, `CapabilityEstimate`, `GapAnalysis`, `MaintenancePlan`) in v1; institutional certification artifacts (`CertificationSnapshot`, `RecertificationPolicy`, `EvidenceDecayPolicy`) deferred until institutional or evaluation scope enters.
- Minimum Demo Criterion at Milestone 4 end: 10 notes → 30 prompts → review queue with reason codes → study-coach session per topic → day-30 retention check on at least three items.

## Review Notes

The next reviewer should evaluate:

- whether the product architecture follows from the research rather than merely naming research concepts;
- whether the domain model is still too broad for a first implementation;
- whether the early implementation path is concrete enough;
- whether the LLM interaction policy is specific enough to drive implementation and evaluation;
- whether graph, mastery, certification, and evidence models are coherent together;
- whether data boundaries and privacy assumptions need stronger treatment before implementation.
