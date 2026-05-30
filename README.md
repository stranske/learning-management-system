# Learning Management System

An API-first learning management system for evidence-informed personal learning, investment analyst training, company-wide project and technology onboarding, and public-facing education.

The project starts from a learning-science premise: an LMS should not merely host content. It should help learners build durable, usable knowledge through retrieval, elaboration, spaced practice, feedback, transfer, and self-regulated learning. The early design work is anchored in *How Do We Learn?: A Scientific Approach to Learning and Teaching* by Hector Ruiz Martin, supplemented by primary research from cognitive science and educational psychology.

## Product Vision

This system will support four major audience families:

- Personal learning: a structured environment for turning reading, notes, and projects into durable knowledge.
- New analyst training: a controlled curriculum for investment philosophy, firm strategies, research workflows, data practices, and decision standards.
- Company-wide learning: repeatable onboarding and continuing education for internal projects, technology, processes, and operating norms.
- Public education: client- or community-facing learning paths that explain products, services, and domain concepts while giving the organization aggregate feedback on public understanding.

The initial implementation target is an API-first backend. A web application is a planned product surface, but the backend should define the core learning model, data contracts, assessment engine, scheduling logic, and analytics before the UI becomes the primary driver.

## Design Commitments

Every major feature should map to a learning principle, an observable learner action, and a measurable outcome.

| Learning principle | Product commitment |
| --- | --- |
| Learning depends on meaningful mental activity | Lessons must ask learners to explain, compare, classify, predict, solve, or apply, not just consume content. |
| Retrieval strengthens durable memory | Courses should include low-stakes recall, practice questions, case prompts, and cumulative checks. |
| Spacing improves retention | The platform should schedule review over time and reintroduce important ideas in later contexts. |
| Working memory is limited | Content should be chunked, sequenced, scaffolded, and paired with examples before complex performance tasks. |
| Feedback guides improvement | Feedback should tell learners the goal, current gap, and next action, not merely mark work right or wrong. |
| Transfer requires varied practice | Analyst and employee training should use realistic cases, edge cases, and scenario variation. |
| Learners need metacognitive calibration | The system should compare confidence, performance, and time to reveal overconfidence and weak areas. |
| Motivation and self-regulation affect persistence | Learners should see goals, progress, next actions, and reflection prompts without turning learning into shallow gamification. |
| Evidence beats intuition alone | Design decisions should be tracked in a research register and revised when evidence or product data warrants it. |

## Planned System Modules

### Learning Object Model

Defines the durable units of learning:

- Concepts: atomic ideas, definitions, models, and distinctions.
- Procedures: repeatable workflows and operating steps.
- Cases: realistic decisions, examples, postmortems, and simulations.
- Assessments: retrieval prompts, application tasks, reflections, and performance rubrics.
- Competencies: observable capabilities tied to roles, goals, or domains.

### Content and Curriculum API

Stores courses, modules, prerequisites, learning objectives, source references, internal ownership, and publication status. This should support both personal material and controlled firm training content.

### Knowledge Graph and Graph Design

Represents institution-designed and learner-authored knowledge graphs, including prerequisites, transfer contexts, competency relationships, and graph-improvement signals from learner performance.

### Retrieval and Assessment Engine

Generates and serves quizzes, free-recall prompts, case questions, confidence ratings, and applied tasks. Assessment should be treated as a learning activity, not just a certification event.

### LLM Learning Interaction Layer

Supports guided learning conversations, exploration, practice, transfer prompts, and authoring assistance while enforcing formative-learning policies and learner controls for feedback nudges.

### Spaced Review Scheduler

Schedules review based on importance, prior performance, confidence, elapsed time, and target mastery. This should eventually support adaptive spacing without hiding the rationale from learners or administrators.

### Feedback and Rubric System

Supports answer-level feedback, rubric-based review, model answers, hints, and next-step recommendations. For analyst training, rubrics should capture reasoning quality, evidence use, risk awareness, and investment judgment.

### Scenario and Simulation Layer

Provides realistic analyst cases and employee workflow simulations. Examples include manager research, strategy selection, data-quality triage, investment memo review, technology rollout decisions, and incident response.

### Learner Model and Analytics

Tracks progress, mastery estimates, retrieval history, confidence calibration, time-on-task, forgotten items, and competency coverage. Analytics should help learners and managers decide what to do next.

### Current Capability and Gap Analysis

Estimates what a learner appears to know and be able to do right now, how confident the system is, how that compares with a target, and what learning path would close the gap.

### Administration, Governance, and Security

Controls roles, access, sensitive content boundaries, audit trails, data retention, and separation between personal learning data and firm training records.

## Repository Structure

Current documentation structure:

```text
.
|-- README.md
|-- docs/
|   |-- README.md
|   |-- project-review-brief.md
|   |-- product/
|   |   |-- project-plan.md
|   |   |-- early-design-decisions.md
|   |   |-- development-testing-surfaces.md
|   |   `-- research-domain-model.md
|   |-- research/
|   |   |-- learning-principles.md
|   |   |-- references.md
|   |   |-- kindle-source-notes.md
|   |   |-- math-academy-way-outline.md
|   |   |-- math-academy-way/
|   |   `-- section and chapter summaries
```

Planned implementation structure after repo setup:

```text
.
|-- src/
|   `-- lms/
|       |-- api/
|       |-- auth/
|       |-- curriculum/
|       |-- evidence/
|       |-- feedback/
|       |-- graphs/
|       |-- llm/
|       |-- mastery/
|       |-- scheduling/
|       `-- analytics/
|-- tests/
|-- scripts/
|-- tools/
|-- config/
`-- .github/
    |-- workflows/
    `-- codex/
```

## Research Register

The working research register is in [docs/research/learning-principles.md](docs/research/learning-principles.md). It links principles from the book and related research to concrete LMS design implications.

Supporting research artifacts:

- [Documentation index](docs/README.md): organized map of product and research docs for local review.
- [Project review brief](docs/project-review-brief.md): handoff summary for a second local-agent review.
- [Research references](docs/research/references.md): reusable bibliography and claim support notes.
- [LMS project plan](docs/product/project-plan.md): implementation-facing design structure, module map, roadmap, backlog sequence, and decision questions.
- [Early design decisions](docs/product/early-design-decisions.md): segmented decision queue for narrowing scope before implementation.
- [Development testing surfaces](docs/product/development-testing-surfaces.md): lightweight UI surfaces needed to test the learning loop during development.
- [Research-to-product domain model](docs/product/research-domain-model.md): initial conceptual schema for principles, evidence, interventions, outcomes, and experiments.
- [The Math Academy Way outline](docs/research/math-academy-way-outline.md): index for the detailed batch outline of the Math Academy working draft.
- [The Math Academy Way detailed worklog](docs/research/math-academy-way/README.md): chapter inventory, batch status, and completed outline batches.
- [The Math Academy Way and How Do We Learn? synthesis](docs/research/math-academy-way/synthesis-with-how-do-we-learn.md): common understanding, tensions, unique contributions, LMS implications, and claim-review register.
- Current book/section summaries: [Chapter 1](docs/research/chapter-01-scientific-study-summary.md), [Section 2.1](docs/research/chapter-02-components-of-memory-summary.md), [Section 2.2](docs/research/section-02-02-organization-of-memory-summary.md), [Section 2.3](docs/research/section-02-03-memory-processes-summary.md), [Section 2.4](docs/research/section-02-04-reorganization-of-memory-summary.md), [Section 2.5](docs/research/section-02-05-transfer-of-learning-summary.md), [Section 2.6](docs/research/section-02-06-working-memory-summary.md), [Section 2.7](docs/research/section-02-07-deep-learning-summary.md), [Section 3.1](docs/research/section-03-01-role-of-emotions-in-learning-summary.md), [Section 3.2](docs/research/section-03-02-motivation-summary.md), [Section 3.3](docs/research/section-03-03-beliefs-summary.md), [Section 3.4](docs/research/section-03-04-social-dimension-of-learning-summary.md), [Section 4.1](docs/research/section-04-01-metacognition-summary.md), [Section 4.2](docs/research/section-04-02-self-control-summary.md), [Section 4.3](docs/research/section-04-03-emotional-self-regulation-summary.md), [Section 4.4](docs/research/section-04-04-resilience-and-grit-summary.md), [Section 5](docs/research/section-05-key-teaching-processes-summary.md), [Section 5.1](docs/research/section-05-01-instruction-summary.md), [Section 5.2](docs/research/section-05-02-feedback-summary.md), [Section 5.3](docs/research/section-05-03-assessment-summary.md), [Appendix](docs/research/appendix-pseudoscientific-myths-summary.md).

The Kindle extraction notes are in [docs/research/kindle-source-notes.md](docs/research/kindle-source-notes.md). Current local Kindle data shows:

- 192 personal highlight records for the book in the newer Kindle annotation database.
- 10 popular-highlight text records in the legacy annotation store.
- Personal highlight records include positions and timestamps, but not the highlighted text in the inspected database.
- Popular highlights are useful as signals, but they must be labeled separately from personal annotations.

## Running The Backend Locally

The Milestone 1 backend skeleton ships as the Python package `lms` under `src/lms/`. To start the FastAPI development server:

```bash
uv sync --extra dev          # install runtime + dev dependencies into .venv
uv run python -m lms          # start uvicorn on http://127.0.0.1:8000 with reload
```

Useful endpoints once the server is running:

- `GET /health` — returns `{"status": "ok", "app": "lms", "version": "<package version>"}`.
- `GET /docs` — interactive Swagger UI for the current router tree.
- `GET /openapi.json` — OpenAPI schema (also covered by `tests/api/test_health.py`).

Run the test suite with `uv run pytest`. The skeleton modules under `src/lms/` (`api`, `auth`, `curriculum`, `evidence`, `feedback`, `graphs`, `llm`, `mastery`, `scheduling`, `analytics`) are intentionally empty placeholders so later milestones can attach domain models, routers, and services without reshaping the package layout.

## Deployment

The LMS deploys on Render via the Blueprint at `render.yaml` (FastAPI web
service + Postgres). See [`docs/development/deployment.md`](docs/development/deployment.md)
for the one-time setup (connect repo, set secrets, create the first user)
and [`docs/architecture/auth.md`](docs/architecture/auth.md) for the password
authentication design.

Once deployed, the service URL is shown in the Render dashboard
(e.g. `https://learning-management-system.onrender.com`). The deployed
instance enforces Argon2 password login; create the bootstrap user via:

```bash
python -m lms auth create-user --username YOU --display-name "Your Name" --password
```

For local development, [`docs/development/local-setup.md`](docs/development/local-setup.md)
covers `docker compose up` and the native-venv flow.

## Development Workflow

The project is intended to become a GitHub repository using the local Workflows system in `/Users/teacher/Library/CloudStorage/Dropbox/Learning/Code/Workflows`.

Planned setup:

- Initialize this folder as a Git repo.
- Create the GitHub repository when the project name is final enough.
- Copy the Workflows consumer template files needed for CI, issue intake, agent automation, and verification.
- Use GitHub issues as structured implementation units.
- Use acceptance criteria that connect product behavior to learning-science intent.
- Keep research, product, and architecture decisions in docs before broad implementation.

Example issue shape:

```text
Goal: Implement retrieval-practice prompt records.

Why: Retrieval should be a first-class learning activity, not just a quiz result.

Scope:
- Add backend model for retrieval prompts.
- Support prompt type, target concept, expected answer form, difficulty, and feedback hooks.
- Add tests for creation and retrieval.

Acceptance criteria:
- API can create and retrieve a prompt tied to a learning objective.
- Prompt records can be scheduled for later review.
- Documentation states which learning principle the feature supports.
```

## Early Milestones

See [docs/product/project-plan.md](docs/product/project-plan.md) for the authoritative milestone definitions with deliverables and acceptance criteria. Summary:

1. **Milestone 0** — Repo and decision foundation (`stranske/Template` consumer setup, Workflows scaffolding, initial backlog).
2. **Milestone 1** — Backend skeleton (FastAPI / Postgres / migrations / CI / health check / auth placeholder).
3. **Milestone 2** — Research registry (YAML) + `SourceReference` + Markdown/CSV importers + drift-detection.
4. **Milestone 3** — Knowledge graph (with `ownership_scope`), evidence records (verbose schema), `MasteryEstimate` as a computed view (FSRS-4.5 placeholder), Inspect surface, v1 export/import contract.
5. **Milestone 4** — Retrieval, review queue with FSRS adapter and sustainability features, LLM client wrapper with cost monitoring and trace classification, formative `study-coach` / `practice` modes. **End-of-milestone gate: the Minimum Demo Criterion runs end-to-end on the project owner's personal-research-note slice with a pre-registered day-30 retention test.**
6. **Milestone 5** — Feedback, rubrics, transfer cases; personal gap-closing artifacts (`CapabilityTarget`, `CapabilityEstimate`, `GapAnalysis`, `MaintenancePlan`).
7. **Milestone 6** — Authoring and learner web prototype (mobile-friendly); begin empirical mastery-rule tuning.
8. **Milestone 7** — Analyst training pilot (one competency, one work product, separate deployment when firm scope enters).
9. **Milestone 8** — Public education and accessibility pilots.

Phase 1 (Milestones 0-4) targets the 11-entity minimum core (`User`, `Learner`, `KnowledgeNode`, `KnowledgeEdge`, `SourceReference`, `Prompt`, `Attempt`, `EvidenceRecord`, `ReviewQueueItem`, `LearningGoal`, `LLMSession`). `Course`/`Module`/`Lesson`, full `FeedbackRecord` table, runtime research-registry APIs, and certification artifacts (`CertificationSnapshot`, `RecertificationPolicy`, `EvidenceDecayPolicy`) are explicitly deferred.

## Open Decisions

Still open:

- Final repository name.
- Initial analyst-training curriculum scope (one competency, one work product, picked once the personal-learning slice is running).
- How much Kindle-derived material should be manually re-highlighted or exported before becoming part of the research register.
- Realistic daily/weekly attempt volume for the project owner — answered empirically at Milestone 4-5 from ~30 days of real use.
- Per-mode LLM model defaults — answered empirically once the eval gold set and cost data exist.
- Specific FSRS-4.5 parameter adjustments per knowledge type — answered empirically from ~500-1000 evidence records on overlapping nodes (Milestone 6-7).

Resolved during the second-review-pass design:

- Repository name: `learning-management-system`.
- Repository visibility: public. Research-note content (chapter/section summaries of *How Do We Learn?*, Math Academy outline and synthesis, Kindle-derived highlights) is kept in a separate local folder and is **not** committed to the public repo. The public repo carries product/design docs, code, the principles register (paraphrase-only), and references; copyright-restricted-to-paraphrase content stays local. The split is reversible (can convert the repo to private later, or move local notes in) and is a Milestone-0 decision when the repo is created.
- License: to be selected at repo creation. Default candidates: MIT for permissive engine code, or CC-BY-4.0 for design docs. Decide at `gh repo create` time.
- Repo creation mechanism: use the `stranske/Template` GitHub template-repository (or the equivalent SETUP_CHECKLIST.md procedure under `Workflows/docs/templates/`) so consumer-template workflow files arrive pre-installed; the new repo is then registered for ongoing sync via `maint-68-sync-consumer-repos.yml`.
- Backend stack: Python, FastAPI, SQLAlchemy, Alembic, Pydantic, pytest, Jupyter/pandas for analysis.
- Persistence: Postgres first.
- Authentication: local auth first for personal use; SSO-ready identity model.
- Personal vs. firm boundary: schema-level `ownership_scope` enforced; cross-scope links explicit; separate deployments preferred over multi-tenant rows when firm content enters scope.
- Mastery rule for v1: FSRS-4.5 placeholder; `MasteryEstimate` is a computed view; empirical tuning at Milestone 6-7.
- Certification: personal gap-closing (`CapabilityTarget`, `CapabilityEstimate`, `GapAnalysis`, `MaintenancePlan`) in v1; institutional certification artifacts deferred.
- LLM posture: single client wrapper, per-mode model config, daily cost monitoring, budget kill-switch, trace-class retention, Anthropic API with no training opt-in, eval gold set required before first study-coach flow.
- Inspect surface: built in Milestone 3 to debug the engine, not deferred.
- Export/backup contract: shipped in v1.
- Mobile: mobile-friendly default on every UI surface; PWA on the roadmap.
