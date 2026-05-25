# Phase 1 Convergence Report — Codex Design Review

Status: Codex round-1 complete; Claude (this agent) response below. Awaiting project owner adjudication before doc updates and Phase 2 begin.

## Summary

Codex produced 12 findings across 10 topics. Categories: 6 push-backs, 3 new-concerns, 3 open-questions. No `agree` findings — consistent with the brief, which asked Codex to surface gaps rather than reinforce agreements.

**Codex's overall assessment:** "The design is coherent at the thesis level... The main blocking concern is not architecture choice but specification hygiene: make Phase 1 scope, source/import/export contracts, evidence fields, FSRS adapter behavior, and privacy enforcement explicit before generating implementation issues."

**Claude's overall assessment:** Agree. All 12 findings are valid and well-grounded. None push back on the architectural direction; they push back on specification completeness. The work generates ~1500-2500 lines of doc additions across ~6 files, none of which require new conversations with the project owner — with three exceptions (findings 5, 9, 12) where the owner's input on a specific default would be useful.

## Per-finding adjudication

For each: Codex's summary, Claude's position, proposed action, whether owner adjudication is needed beyond "go ahead."

### 1. `scope-001` — Phase 1 trim not consistently reflected across docs

- **Category:** push-back / schema-trim
- **Codex:** The trimmed Phase 1 model conflicts with older sections (README Early Milestones, project-plan API sketch, Milestone 2 deliverables, dev-testing-surfaces authoring surface). Agents will be confused about whether to implement the trimmed learner loop or the older curriculum-first design.
- **Claude:** Agree completely. The second-pass updates hit the load-bearing sections but missed several mentions. Codex's cited line ranges are accurate.
- **Action:** Sweep `README.md` (Early Milestones), `project-plan.md` (Initial Product Boundary, API Surface Sketch, Milestone 2), `development-testing-surfaces.md` (Surface 3 Authoring) so all mentions of Phase 1 scope center the 10-entity list. Mark course/module/lesson UI clearly as later-milestone.
- **Owner input needed:** No.

### 2. `source-001` — `SourceReference` should be Phase 1 entity

- **Category:** new-concern / source-citation
- **Codex:** Required by prompts, imports, drift detection, and export, but not listed as Phase 1 entity. Hides the need for stable identity, hash algorithm/version, source visibility, drift status, and multi-source roles.
- **Claude:** Agree. Multiple prompts may cite the same passage (reuse); drift detection lives at the SourceReference level; audit log for source edits needs identity. Promoting it brings Phase 1 from 10 to 11 entities.
- **Action:** Add `SourceReference` to Phase 1 list with fields: `source_type`, `stable_locator`, `passage_range`, `content_hash`, `hash_algorithm` (default `sha256`), `source_visibility` (`public` / `local-only`), `drift_status` (`current` / `stale` / `missing`), `multi_source_role` (`primary` / `supporting` / `counterpoint`).
- **Owner input needed:** No.

### 3. `evidence-001` — EvidenceRecord schema needs more fields for future learned models

- **Category:** push-back / mastery-rule
- **Codex:** Missing prompt version, item difficulty/discrimination proxies, scoring method, raw/normalized/max score, partial-credit dimensions, rater/judge identity/version, attempt context, validity scope, answer artifact reference. Without these, future tuning learns artifacts of prompts and graders rather than learner state.
- **Claude:** Agree. The original list was strong for spaced-review but light on assessment-grade evidence. This is the most important finding because `EvidenceRecord` is the load-bearing v1 schema decision.
- **Action:** Expand the `EvidenceRecord` schema in project-plan.md Mastery section and Retrieval And Assessment Engine. Add: `prompt_version_id`, `scorer_type`, `scorer_id`, `scorer_version`, `scoring_method`, `raw_score`, `normalized_score`, `max_score`, `partial_credit_dimensions` (JSON), `item_difficulty_estimate` (nullable placeholder), `attempt_context` (session id, device class, UI mode), `validity_scope`, `answer_artifact_ref`.
- **Owner input needed:** No.

### 4. `mastery-002` — `MasteryEstimate` materialization threshold needed

- **Category:** open-question / mastery-rule
- **Codex:** Computed view is right, but no materialization threshold or cache policy specified. Inspect, scheduler, and gap analysis all read estimates frequently. Risk: overbuild materialization or ship slow scheduler.
- **Claude:** Agree. The design should name the trigger rather than leave it to issue-generation time.
- **Action:** Add a paragraph to project-plan.md Mastery section: recompute on demand for Phase 1; optional materialized cache after measured latency threshold (e.g., ≥200ms p99) OR record count threshold (≥10,000 EvidenceRecord rows per learner); cached estimates store `estimator_version` and `generated_at`.
- **Owner input needed:** No.

### 5. `scheduler-001` — Need `SchedulerEvidenceAdapter` (EvidenceRecord → FSRS rating mapping)

- **Category:** push-back / sustainability
- **Codex:** FSRS expects 4-grade review ratings (Again/Hard/Good/Easy); LMS logs heterogeneous evidence. Without an explicit adapter, agents will improvise inconsistent mappings.
- **Claude:** Agree, and an excellent catch I missed. Specifying as an explicit rule table with tests makes the scheduler swappable later.
- **Action:** Add a "SchedulerEvidenceAdapter" subsection to project-plan.md Review Scheduler with a starter rule table:
  - `correctness=incorrect` → Again
  - `correctness=correct AND (hint_used OR reference_used OR support_level ≥ medium)` → Hard
  - `correctness=correct AND confidence ≤ low` → Hard
  - `correctness=correct AND confidence ≥ medium AND no hints/refs/support` → Good
  - `correctness=correct AND first_attempt AND confidence=high AND fast_response` → Easy
  - Partial-credit items: pre-threshold the normalized score (≥0.85 → Good, 0.5–0.85 → Hard, <0.5 → Again)
  - Transfer items: ratings recorded but excluded from FSRS scheduling until a separate transfer scheduler exists.
- **Owner input needed:** **Yes — adjudication welcome on the rule table before I commit it to the doc.**

### 6. `privacy-001` — Privacy must enforce local-first redaction before external tracing

- **Category:** push-back / privacy
- **Codex:** Classification alone doesn't prevent PII reaching LangSmith. Need: classify-and-redact locally before external trace, default `ephemeral` to no verbatim external trace, define deletion propagation, distinguish transcript deletion from retained structured evidence.
- **Claude:** Agree. The current design implicitly sends raw traces to LangSmith and then expects classification to catch them post-hoc, which is the wrong order.
- **Action:** Edit Segment 9 and the LLM Operational Requirements:
  - "Classification and PII redaction happen locally before any external trace export. The LLM client wrapper holds a redactor that runs on every outbound trace payload before LangSmith ingestion. Failed redaction → trace class demoted to `ephemeral` and held locally."
  - "`ephemeral` traces are never exported verbatim. Only structured outcomes (correctness, confidence, evidence id refs) persist."
  - "Learner `forget` action triggers (a) local trace deletion, (b) LangSmith deletion via API where supported, (c) preservation of structured evidence records (which do not contain verbatim transcript)."
- **Owner input needed:** No.

### 7. `ownership-001` — Schema column needs enforcement primitives

- **Category:** push-back / ownership-scope
- **Codex:** `ownership_scope` as a column doesn't enforce query/analytics safety. Need scoped query helpers, aggregation tests, cross-scope `GraphReference` constraints, later Postgres RLS decision.
- **Claude:** Agree. Schema-level enforcement is necessary but not sufficient.
- **Action:** Add "Ownership-boundary enforcement" subsection to project-plan.md Knowledge Graph:
  - Repository pattern: all queries accept an explicit `scope` parameter; no implicit scope inference.
  - Cross-scope joins require a `GraphReference` row; database `CHECK` constraint enforces matching `ownership_scope`.
  - Test suite: explicit aggregation tests that attempt cross-scope contamination on mastery summaries, scheduler reads, Inspect surface, and verify they fail or produce only scope-pure results.
  - Future: Postgres Row-Level Security at institutional deployment time; deferred until needed.
- **Owner input needed:** No.

### 8. `export-001` — Export contract underspecified

- **Category:** new-concern / ui-and-export
- **Codex:** "JSONL and re-importable" isn't a contract. Need schema versioning, stable IDs, dependency ordering, redaction modes, import validation path.
- **Claude:** Agree.
- **Action:** Replace the export bullet with a contract subsection in project-plan.md Milestone 3:
  - Format: newline-delimited typed records (`{"type": "<entity>", "schema_version": <int>, "record": {...}}`).
  - Stable IDs preserved; foreign-key references use the same IDs.
  - Records ordered so dependencies come first (entities before relationships).
  - Redaction modes: `--include-llm-traces=evidence-grade-only` (default), `--include-source-content=public-only` (default; keeps local-only research content excluded), `--include-pii=never` (default).
  - `lms import --dry-run <file>` validates schema and FK integrity without writing; `lms import --apply <file>` writes. Both ship in v1.
- **Owner input needed:** No.

### 9. `demo-001` — Day-30 retention criterion not falsifiable

- **Category:** push-back / minimum-demo
- **Codex:** "Three items the learner would not otherwise have retained" is not measurable. Proposes a pre-registered protocol: candidate items, initial confidence + unaided attempt recorded, some scheduled some held as comparison, day-30 delayed retrieval test.
- **Claude:** Agree completely. The current language is satisfying-narrative-only.
- **Action:** Replace Minimum Demo Criterion item 6 with the pre-registered protocol. Add to Milestone 4 deliverables: "Demo retention protocol document at `docs/handoff/demo-retention-protocol.md` written before any prompts are authored; pre-registers items, intended comparison, and day-30 test."
- **Owner input needed:** **Yes — please weigh in on the protocol shape.** Claude's default proposal: **8 items**, **4 system-scheduled** (full loop: prompt + review + study-coach), **4 held-as-comparison** (read passively, no system intervention), **day-30 unaided free-recall test** on all 8 — protocol pre-registered before the items are picked. OK as default, or adjust?

### 10. `llm-001` — LLM wrapper underspecified

- **Category:** new-concern / llm-cost
- **Codex:** Thin model-selection wrapper isn't enough. Needs: mode config resolution, budget preflight, retry/timeouts, optional streaming, structured-output validation, token/cost accounting, trace-class metadata, source constraints, eval replay hooks.
- **Claude:** Agree. Codex's list is the right scope.
- **Action:** Add "LLM client wrapper interface (v1)" subsection to project-plan.md LLM Operational Requirements:
  - Method: `complete(mode, prompt, *, structured_output_schema=None, trace_class, source_constraints, max_tokens, ...) -> LLMResponse`
  - Pre-call: budget check (per-mode + global daily); raise if exceeded.
  - Call: provider routing per `mode` config; retries with exponential backoff; configurable timeout.
  - Post-call: token/cost accounting (provider-normalized); trace-class metadata attached; PII redaction; LangSmith export per trace class; response validation against structured schema if provided.
  - Eval replay: `replay(gold_set_entry, mode_override) -> LLMResponse` for replaying historical inputs against current model/prompt config.
- **Owner input needed:** No.

### 11. `research-001` — Research registry still has runtime API in older sections

- **Category:** push-back / schema-trim
- **Codex:** Phase 1 trim says YAML-only, but Milestone 2 still requires research registry CRUD APIs and research-domain-model still sketches API resources.
- **Claude:** Agree, bundle with Finding 1's sweep.
- **Action:** Update Milestone 2 (replace "research registry CRUD" with "YAML schema + validator + reference linter"); add a clarifying header to `research-domain-model.md` noting it's the conceptual schema for the YAML files, not runtime DB tables; remove `/research/*` from the v1 API surface sketch (move to a "later" section).
- **Owner input needed:** No.

### 12. `graph-001` — Knowledge graph bootstrap path needs picking

- **Category:** open-question / other
- **Codex:** Brief itself flagged the first 50 nodes path as uncertain. Without a chosen path, issue writers may overbuild graph authoring or underbuild import tooling. Proposes: Markdown/CSV import for draft nodes, optional LLM-proposed drafts, human approval required.
- **Claude:** Agree. Codex's path is a reasonable v1 default.
- **Action:** Add "Knowledge Graph Bootstrap (v1)" subsection to project-plan.md Knowledge Graph:
  - Importers (Milestone 2): Markdown files → draft `KnowledgeNode` per H1/H2 heading with `SourceReference` linking to heading anchor; CSV files → drafts with explicit columns for node title, type, prerequisite list.
  - Optional `authoring-assist` LLM mode (Milestone 4): proposes additional nodes and edges from existing drafts; requires human approval per item before publishing.
  - Drafts can be referenced by prompts only after publishing (no scheduler reads against draft nodes).
  - Audit log records `imported_from`, `proposed_by`, `approved_by`, `approved_at`.
- **Owner input needed:** **Yes — if you have specific source material in mind (e.g., existing OPML outlines, a particular note structure) that suggests a different starting form, say so. Otherwise Markdown+CSV import is the v1 default.**

## Cumulative scope of doc edits

Estimating ~1500-2500 lines across:

- `README.md` (small — Early Milestones consistency)
- `docs/README.md` (small — list updates)
- `docs/product/project-plan.md` (large — Mastery, Retrieval, Knowledge Graph, Review Scheduler, LLM Layer, Phase 1 entity list, Milestone 2, Milestone 3, Milestone 4, API surface, Minimum Demo)
- `docs/product/early-design-decisions.md` (medium — Segment 9 strengthening; minor Segment 6 housekeeping)
- `docs/product/development-testing-surfaces.md` (small — Surface 3 consistency, Surface 5 mastery-attribution detail)
- `docs/product/research-domain-model.md` (small — clarifying header)

Plus one new file (later): `docs/handoff/demo-retention-protocol.md` — drafted during Milestone 4 prep, not now.

Nothing changes the project's architecture, scope, or major decisions. It's all specification hygiene per Codex's overall assessment.

## What's needed from the project owner

1. **Finding 9 (demo protocol shape):** 8 items / 4 scheduled / 4 held-as-comparison / day-30 unaided free-recall — OK as default, or adjust?
2. **Finding 5 (FSRS adapter rule table):** OK as starting point, or modify before commit to doc?
3. **Finding 12 (graph bootstrap):** Markdown+CSV import OK as v1 default, or different source material in mind?
4. **Anything else:** push-backs on Codex's findings, tightening on Claude's resolutions, or anything Codex missed worth surfacing before incorporation?

Once adjudicated, Claude incorporates all 12 findings into the design docs, then Phase 2 (issue generation) runs against the now-consistent design.
