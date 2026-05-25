# Codex Design Review Brief — Learning Management System

Status: handoff brief for parallel-agent design review before repo creation.

## Purpose

This brief sets up a Codex-side design review of the Learning Management System project before the GitHub repo is created. It is paired with a Claude-side review running in parallel. The two reviews converge via the `repo_review_coordinator.py` pattern (file-mediated, synthesizer-reconciled), producing a convergence packet for the project owner to adjudicate. After agreement is reached on the design, the same pattern is reused for Phase 2 (collaborative issue generation against the agreed design), producing the initial Milestone-0-to-4 issue queue in `AGENT_ISSUE_FORMAT.md` shape.

The GitHub repo is not created until both phases converge.

## Local Context

- Project folder: `/Users/teacher/Library/CloudStorage/Dropbox/Learning/Code/Learning-Management-System/`.
- Current state: documentation and design only. No application code. Not a git repo.
- Workflows source-of-truth: `/Users/teacher/Library/CloudStorage/Dropbox/Learning/Code/Workflows/`.
- Consumer template repo: `stranske/Template` (used as GitHub template-repository source when the new repo is created).
- Related: `/Users/teacher/Library/CloudStorage/Dropbox/Learning/Code/Workflows-steward/` for repo-review pipeline scripts.

## TL;DR

The project is an API-first **learning engine** (not a content host) intended to support several audiences over time — personal learning from research notes (first), new analyst training, company-wide onboarding, public pension client education, and accessibility-sensitive learning. The design is grounded in Ruiz Martin's *How Do We Learn?* (evidence hygiene + learning mechanisms) and Skycak's *The Math Academy Way* (implementation pattern library, with Math-Academy-specific product claims preserved as reviewable claims rather than adopted as facts).

The system thesis:

- Content completion is exposure, not learning evidence.
- Learner action must be observable.
- Mastery is a changing current-capability estimate, not a permanent label.
- The scheduler reads learner state, not the calendar.
- Feedback creates a next action.
- LLM interaction is formative, not answer-vending.
- Research claims remain reviewable.

Stack: Python, FastAPI, SQLAlchemy, Alembic, Pydantic, pytest, Postgres, REST/OpenAPI, LangChain/LangGraph + LangSmith, Jupyter/pandas. Local auth first with SSO-ready identity. Consumer workflows via `stranske/Template`.

## Repo Setup Decisions Already Made

- Repository: `stranske/learning-management-system`.
- Visibility: public.
- Research-note content (chapter/section summaries of *How Do We Learn?*, Math Academy outline and synthesis, Kindle-derived highlights) stays in the current local folder, gitignored in the public repo. The split is reversible.
- License: to be selected at `gh repo create` time. Default candidates: MIT for code, CC-BY-4.0 for docs.
- Repo creation: `gh repo create stranske/learning-management-system --template stranske/Template --public`. Consumer workflows arrive pre-installed; `maint-68-sync-consumer-repos.yml` keeps them current after registration.
- Local clone path: `learning-management-system` (lowercase, renamed from current `Learning-Management-System`).

## Second-Review-Pass Decisions

These are the new design positions that emerged from the second review with the project owner. Each is captured in detail in the linked docs; the summary below names the tension that produced the decision and where Codex review would be especially useful.

### 1. Mastery rule from data, not first principles

**Tension:** Calibrating a mastery model from first principles produces elegant formulas no one trusts; calibrating from real evidence requires running the system first.

**Decision:** Ship v1 with FSRS-4.5 (default parameters) as a deliberately throwaway placeholder. `MasteryEstimate` is a **computed view** over `EvidenceRecord` history, not a separately-written table. The verbose `EvidenceRecord` schema is the load-bearing v1 decision — log every signal a future learned model could want (timestamp, prompt id, prompt demand level, knowledge type, time since last attempt, response time, correctness, confidence rating, hint use, reference use, support level, retrieval demand, transfer distance, source-match quality). Empirical tuning lands at Milestone 6-7 when ~500-1000 evidence records exist on overlapping nodes.

**Codex review focus:**
- Is the `EvidenceRecord` schema as listed actually sufficient for a future learned model (Bayesian Knowledge Tracing, IRT, Elo-style, half-life regression, or learned FSRS parameters)? What's missing?
- Should the placeholder be Leitner instead of FSRS for v1? FSRS is more capable but more parameters; Leitner is brain-dead simple. Which serves the data-collection-with-honest-defaults goal better?
- Does `MasteryEstimate` as a computed view scale acceptably as records accumulate, or do we need materialized incremental updates from day one?

**Doc refs:** `docs/product/early-design-decisions.md` Segment 2; `docs/product/project-plan.md` "Mastery Is An Evidence-Backed Estimate" commitment; "Phase 1 Minimum Core" notes.

### 2. Personal-learning sustainability before cadence tuning

**Tension:** The scheduler cadence question is partly downstream of how much the project owner actually uses the system — an empirical question. But the system needs sensible defaults so interruption doesn't make it unusable.

**Decision:** v1 ships pause/vacation mode, daily cap (~20-30 items default), and stale-item handling. FSRS-4.5 defaults with a low new-card introduction rate. The cadence-tuning decision is deferred to Milestone 4-5, after ~30 days of real use.

**Codex review focus:**
- Does the sustainability set cover Anki's known failure modes (the 500-card-after-vacation backlog being the canonical one)?
- Stale-item handling — what's the right UX so it surfaces re-engagement / retire / adjust-goal options without shame?

**Doc refs:** `docs/product/early-design-decisions.md` Segment 8; `docs/product/project-plan.md` "Review Scheduler" section "Initial scheduler rule."

### 3. Certification artifacts deferred; personal gap-closing in v1

**Tension:** Certification-as-product-feature is intellectually central but not useful when one learner is evaluating themselves.

**Decision:** `CapabilityTarget`, `CapabilityEstimate`, `GapAnalysis`, `MaintenancePlan` ship in v1. `CertificationSnapshot`, `RecertificationPolicy`, `EvidenceDecayPolicy` deferred until institutional or evaluation scope enters.

**Codex review focus:**
- Is the personal gap-closing flow actually usable without the certification machinery, or does some of it need to come along?
- "Gap-closing" for personal learning will sometimes mean "I want to deepen understanding of strategy X" — a transfer/judgment goal. Does the design handle that case without leaning on certification primitives?

**Doc refs:** `docs/product/early-design-decisions.md` Segment 5; `docs/product/project-plan.md` "Current Capability And Certification" section.

### 4. Privacy and LLM trace classification

**Tension:** Personal-learning LLM sessions will carry half-formed thoughts and possibly sensitive professional or personal reflection. Retention should serve evaluation and decision-making, not collection for its own sake.

**Decision:** Every `LLMSession` declares a `trace_class` (`evidence-grade`, `formative`, `ephemeral`). Class-driven retention; default Anthropic API with no training opt-in; LangSmith retention configured per class; PII detection on write with redaction or class demotion; learner keep/forget overrides.

**Codex review focus:**
- Is the three-class taxonomy operational or bureaucratic? Are there cases that don't fit cleanly?
- What's a reasonable v1 approach to PII detection on write that isn't a research project on its own? (Library suggestions welcome.)
- LangSmith retention configuration: what specific knobs does this require?

**Doc refs:** `docs/product/early-design-decisions.md` Segment 9; `docs/product/project-plan.md` LLM Learning Interaction Layer "Operational requirements."

### 5. LLM cost and routing

**Tension:** Per-mode model selection is an empirical question, but configurability is cheap up front and expensive to retrofit.

**Decision:** Single LLM client wrapper with per-mode model config via env vars (`LLM_MODEL_STUDY_COACH`, `LLM_MODEL_PRACTICE`, `LLM_MODEL_TRANSFER`, `LLM_MODEL_AUTHORING_ASSIST`). Per-mode daily cost log line. Hard budget kill-switch with low default. Eval gold set (10-30 hand-curated transcripts) before first `study-coach` flow ships. Substantive per-mode model choices deferred to data.

**Codex review focus:**
- Is the wrapper interface specified enough? Should the wrapper handle retries, streaming, structured output, or just be a thin model-selection layer?
- Eval gold set structure: how should it be versioned alongside the formative-interaction policy? What schema for the transcripts plus labeled outcomes?
- Does `config/llm_slots.json` and `config/model_registry.json` in the consumer template suggest a pattern we should adopt for the per-mode config?

**Doc refs:** `docs/product/early-design-decisions.md` Segment 10; `docs/product/project-plan.md` LLM Learning Interaction Layer.

### 6. Source citation and prompt provenance

**Decision:** Every `Prompt` carries ≥1 `SourceReference` with `content_hash` at creation. Default authoring path: source-extracted for factual prompts; rubric-based or LLM-judged for conceptual/transfer prompts. Source shown after attempt (never before, except via hint, which is tracked and down-weights evidence). LLM feedback constrained to cite linked sources; uncited claims flagged `unverified`. Every `Prompt` carries `authoring_method` (`human`, `llm-assisted`, `llm-generated`), authoring actor, reviewer, approval timestamp, and (for LLM-authored) `llm_model` and `prompt_template_version`. Audit log on authoring actions.

**Codex review focus:**
- Is the `SourceReference` schema rich enough for multi-source prompts where the canonical answer spans passages?
- What's the right drift detection behavior when `content_hash` mismatches the live source (auto-flag in Inspect tab, but does the prompt stay live until reviewed, or auto-suspend)?
- Should the audit log live in Postgres or in an append-only event log file?

**Doc refs:** `docs/product/project-plan.md` Retrieval And Assessment Engine, "Source citation policy" and "Prompt provenance" subsections.

### 7. Ownership-scope at the schema level

**Decision:** Every `KnowledgeGraph`, `KnowledgeNode`, and `KnowledgeEdge` carries `ownership_scope` (`personal` / `institutional`). Cross-scope references are explicit `GraphReference` links, never edge merges. Personal evidence does not flow into institutional analytics, and vice versa. When firm content enters scope, separate deployments preferred over multi-tenant rows.

**Codex review focus:**
- Does schema-level enforcement need explicit row-level security hooks (Postgres RLS, application-level middleware), or is it sufficient as a query/aggregation discipline?
- The "separate deployments preferred" stance for firm content — does this need more concrete deployment-topology design at this stage, or is it OK to defer?

**Doc refs:** `docs/product/early-design-decisions.md` Segment 7; `docs/product/project-plan.md` Knowledge Graph "Design constraints."

### 8. Inspect surface pulled to Milestone 3; mobile-friendly default; v1 export contract

**Decision:** The Inspect surface (evidence timeline, current mastery per node, scheduler decision log, prompt provenance, source-drift status) ships in Milestone 3, not at the end. Every UI surface is mobile-friendly by default; PWA on roadmap. `lms export --out=jsonl` (or equivalent) ships in v1.

**Codex review focus:**
- Mobile-friendly with what CSS framework? Tailwind, Pico, something else? Or build raw and ship a framework later?
- Export contract: is JSONL the right format? Should it also support a round-trip import for migration / disaster recovery?

**Doc refs:** `docs/product/development-testing-surfaces.md` Design Defaults + Surface 5; `docs/product/project-plan.md` Milestone 3.

### 9. Phase 1 schema trim

**Decision:** Phase 1 Minimum Core entities trimmed from 19 to 10 (`User`, `Learner`, `KnowledgeNode`, `KnowledgeEdge`, `Prompt`, `Attempt`, `EvidenceRecord`, `ReviewQueueItem`, `LearningGoal`, `LLMSession`). `LearningPrinciple`, `LearningClaim`, `EvidenceSource` stay as YAML in `docs/research/` with a build-time validator rather than runtime DB tables. `Course`, `Module`, `Lesson` deferred until institutional curriculum authoring. `FeedbackRecord` starts as a structured field on `Attempt`. `InteractionMode`, `LLMInteractionPolicy` stay as code/config.

**Codex review focus:**
- Is the 10-entity Phase 1 set truly minimal? Is anything missing that would force a painful retrofit later?
- The research-registry-as-YAML decision — is the validator a real piece of v1 tooling, or can it be a Makefile target / pre-commit hook? What's the right boundary between docs and DB for this kind of provenance?

**Doc refs:** `docs/product/project-plan.md` "Data Model Priorities" Phase 1; `docs/product/research-domain-model.md`.

### 10. Minimum Demo Criterion

The v1 thesis is not validated until the project owner can demonstrate, end-to-end on their personal-research-note slice:

1. Import ~10 research notes with `SourceReference` + content hashes.
2. Author or LLM-assist ~30 retrieval prompts with knowledge-type tags and provenance.
3. Attempt the prompts with confidence ratings; verbose `EvidenceRecord` rows produced.
4. View current mastery per node in the Inspect surface; view scheduler review queue with reason codes.
5. Complete one `study-coach` LLM session per topic with formative policy active, trace class set, cost monitored.
6. At day 30, demonstrate retention on at least three items the learner would not otherwise have retained.

This lands at the end of Milestone 4 and disciplines all earlier scope.

**Codex review focus:**
- Is the criterion concrete enough to disqualify scope creep, or does it leave too much room?
- The day-30 retention check is informal. Is a formal-enough version possible without overbuilding measurement infrastructure?

**Doc refs:** `docs/product/project-plan.md` "Minimum Demo Criterion" section.

## What I (Claude) Am Most Uncertain About

In rough priority order; Codex review on these would be especially welcome. These overlap with the per-section "review focus" items above but elevated for visibility:

1. **`EvidenceRecord` schema completeness.** The mastery rule is throwaway; the schema must outlast it. Have we listed enough fields?
2. **Knowledge-graph bootstrap path.** The first 50 nodes from personal research notes — manual? LLM-proposed via authoring-assist with human approval per edge? CSV import from note headings? The docs say "manually reviewed graph drafts" but don't pick a specific bootstrap procedure.
3. **`MasteryEstimate` as computed view.** Is the recompute cost acceptable as records accumulate, or do we need materialized incremental updates from day one? What's the operational threshold?
4. **LLM eval gold set structure.** Is 10-30 transcripts the right target? Structure for storing them so they can be replayed across model/prompt combinations without becoming stale.
5. **PII detection on LLM trace write.** What's a reasonable v1 approach that isn't a research project on its own?
6. **Source-citation for multi-source prompts.** What happens when the canonical answer spans passages from multiple `SourceReference` records?
7. **Mobile/PWA defaults.** CSS framework choice and minimum supported viewport.
8. **Owner-as-author audit log location.** Postgres table vs. append-only event log; which is more retrofit-friendly when institutional/evaluation scope enters?

## Phase 2 — After This Review Converges

The same coordinator pattern (adapted for design-only-no-repo input) runs again, this time producing candidate **implementation issues** for Milestones 0 through 4. Output is a queue of AGENT_ISSUE_FORMAT-compliant issues with Why / Scope / Non-Goals / Tasks / Acceptance Criteria / Implementation Notes, ready to upload to the new GitHub repo via `upload_repo_review_issues.py --apply`.

Codex should plan for that phase. The issues need to be:

- Concrete enough for the keepalive loop to make progress on.
- Sized so the opener cap (5 concurrent opener-owned PRs) makes sense.
- Sequenced toward the Minimum Demo Criterion at Milestone 4.
- Sufficient on their own (each issue specifies enough detail that a fresh agent can act without re-reading the whole design corpus).

## Reading Order

For Codex's first pass, in this order:

1. `README.md` (root) — project framing and resolved decisions.
2. `docs/README.md` — doc map and current design decisions.
3. `docs/product/early-design-decisions.md` — segmented decision queue. Especially Segments 2, 5, 7, 8, 9, 10.
4. `docs/product/project-plan.md` — implementation-facing design. Especially the Mastery commitment, Retrieval section (Source Citation Policy + Prompt Provenance), Review Scheduler, Current Capability And Certification, LLM Operational Requirements, Phase 1 Minimum Core, Minimum Demo Criterion, and Milestone 0-4 deliverables.
5. `docs/product/development-testing-surfaces.md` — Design Defaults section, Surfaces 1, 2, 5, 6.
6. `docs/product/research-domain-model.md` — research-to-product schema (will stay as YAML, not runtime DB).
7. Skim `docs/research/math-academy-way/synthesis-with-how-do-we-learn.md` for the Math-Academy-claims posture and the productive tensions section.

Supporting research (`docs/research/section-*-summary.md`, `docs/research/chapter-*-summary.md`, `docs/research/math-academy-way/part-*.md`) is reference material — read on demand, not cover-to-cover.

## Round-1 Output Format

Codex's round-1 output for this design review should be a JSON file with the following shape, written to `docs/handoff/phase1-codex-findings.json`:

```json
{
  "agent": "codex",
  "phase": "phase1-design-review",
  "generated_at": "<ISO timestamp>",
  "findings": [
    {
      "finding_id": "<short-id>",
      "category": "agree | push-back | new-concern | open-question",
      "topic": "<one of: mastery-rule, sustainability, gap-closing, privacy, llm-cost, source-citation, ownership-scope, ui-and-export, schema-trim, minimum-demo, other>",
      "summary": "<one-sentence>",
      "rationale": "<2-5 sentences with specific doc/line refs where applicable>",
      "design_refs": ["<file>:<section or line range>"],
      "implementation_impact": "<which milestone or schema this would touch>",
      "proposed_resolution": "<concrete: 'no change', 'modify X to Y', 'investigate Z', 'add new doc/segment for W'>"
    }
  ],
  "overall_assessment": "<2-4 sentences: is the design coherent and ready for Phase 2 issue generation, or are there blocking concerns?>"
}
```

The parallel Claude reviewer produces a symmetric file at `docs/handoff/phase1-claude-findings.json`. The synthesizer (a thin variant of `scripts/repo_review_coordinator.py`'s round-2 logic) compares findings by `topic`, computes convergence per finding (both-agree, agree-with-modification, deadlocked), and writes `docs/handoff/phase1-convergence-report.md` for the project owner to adjudicate.

## Post-Convergence

The project owner reads the convergence report and adjudicates. Specifically:

- Deadlocked findings: the owner picks a direction.
- Agreed modifications: I incorporate them into the design docs.
- New concerns or open questions accepted as valid: they become specific design follow-ups before Phase 2.

When the design is agreed, Phase 2 (issue generation) begins. The repo is created only after Phase 2 converges.

End of brief.
