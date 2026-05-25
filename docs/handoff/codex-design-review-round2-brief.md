# Codex Design Review — Round 2 Verification Brief

Status: round-2 verification of round-1 findings after Claude incorporated all 12 into the design docs. Codex is asked to verify each finding's resolution and surface any new concerns the changes introduced.

## Context

You (Codex) ran a round-1 design review against `docs/handoff/codex-design-review-brief.md` and produced 12 findings in `docs/handoff/phase1-codex-findings.json` covering schema-trim consistency, `SourceReference` as Phase 1 entity, `EvidenceRecord` schema gaps, `MasteryEstimate` materialization, FSRS adapter, privacy local-first enforcement, ownership-boundary enforcement, export contract, day-30 demo falsifiability, LLM wrapper interface, research-registry consistency, and graph bootstrap.

Claude reviewed your round-1 findings, agreed with all 12, and produced a convergence report at `docs/handoff/phase1-convergence-report.md` with concrete proposed actions. The project owner adjudicated and approved all proposed resolutions, including the three that requested owner input (Findings 5, 9, 12). Claude then made the doc edits.

This round-2 pass is a verification, not a fresh review. The questions are:

1. Did each finding's edit actually resolve the gap correctly?
2. Did any edit introduce a new concern (regression, contradiction, under-specification)?
3. Is the design now ready for Phase 2 (collaborative issue generation against the agreed design)?

## Inputs

Read in this order:

1. `docs/handoff/codex-design-review-brief.md` — original brief (project context).
2. `docs/handoff/phase1-codex-findings.json` — your round-1 findings.
3. `docs/handoff/phase1-convergence-report.md` — Claude's proposed resolutions and owner adjudication.
4. The updated design docs, focusing on the per-finding pointers below.

## Per-finding resolution pointers

For each finding, the design-doc location(s) where the resolution was added:

### Finding 1 (`scope-001` — Phase 1 trim consistency)
- `README.md` Early Milestones — rewritten to summarize Milestones 0-8 with explicit Phase 1 11-entity list and deferral statement.
- `docs/product/project-plan.md` Initial Product Boundary — list rewritten; `Course`/`Module`/`Lesson`, full `FeedbackRecord` table, and runtime research-registry APIs explicitly deferred.
- `docs/product/project-plan.md` Milestone 2 — fully rewritten to "Research Registry (YAML), Source References, And Importers" with explicit Out-of-Scope section.
- `docs/product/project-plan.md` API Surface Sketch — split into v1 / Phase 2+ blocks; `/research/*` marked deferred indefinitely.
- `docs/product/development-testing-surfaces.md` Surface 3 — split into v1 / Phase 2+ deliverables.

### Finding 2 (`source-001` — `SourceReference` as Phase 1 entity)
- `docs/product/project-plan.md` Phase 1 Minimum Core — `SourceReference` added as 11th entity; full schema specified (`source_type`, `stable_locator`, `passage_range`, `content_hash`, `hash_algorithm`, `source_visibility`, `drift_status`, `multi_source_role`, `captured_at`).
- `docs/product/project-plan.md` Initial Product Boundary — references `SourceReference` as first-class entity.
- `docs/product/project-plan.md` Milestone 2 — `SourceReference` runtime entity + CRUD + drift detection added to deliverables.
- `docs/product/project-plan.md` API Surface Sketch v1 block — `/source-references` resource added.

### Finding 3 (`evidence-001` — `EvidenceRecord` schema expansion)
- `docs/product/project-plan.md` "Mastery Is An Evidence-Backed Estimate" — EvidenceRecord v1 fields list expanded to include `prompt_version_id`, `scorer_type`, `scorer_id`, `scorer_version`, `scoring_method`, `raw_score`, `normalized_score`, `max_score`, `partial_credit_dimensions`, `item_difficulty_estimate`, `attempt_context`, `validity_scope`, `answer_artifact_ref`.

### Finding 4 (`mastery-002` — `MasteryEstimate` materialization threshold)
- `docs/product/project-plan.md` Mastery section — recompute-on-demand for v1; optional materialized cache after measured latency (≥200ms p99) OR record count (~10,000 `EvidenceRecord` rows/learner) threshold; cached entries store `estimator_version` and `generated_at`.

### Finding 5 (`scheduler-001` — `SchedulerEvidenceAdapter`)
- `docs/product/project-plan.md` Review Scheduler — new subsection "SchedulerEvidenceAdapter (EvidenceRecord → FSRS rating)" with the 5-row rule table for Again/Hard/Good/Easy mapping; partial-credit pre-threshold; transfer-item exclusion; implementation as pure function with data-driven config; test requirements.

### Finding 6 (`privacy-001` — local-first redaction)
- `docs/product/project-plan.md` LLM "Operational requirements" — bullet rewritten to explicit local-first enforcement order; redactor in the wrapper runs before LangSmith ingestion; ephemeral never exported verbatim; forget action propagation specified.
- `docs/product/early-design-decisions.md` Segment 9 Recommended default — new bullet specifying local-first enforcement order; ephemeral export rule; forget propagation.

### Finding 7 (`ownership-001` — ownership-boundary enforcement)
- `docs/product/project-plan.md` Knowledge Graph — new subsection "Ownership-boundary enforcement" with four layers (repository pattern, DB CHECK on `KnowledgeEdge`, aggregation test suite, future Postgres RLS).

### Finding 8 (`export-001` — export contract)
- `docs/product/project-plan.md` Milestone 3 — bullet replaced; new subsection "Export and import contract (v1)" specifying NDJSON format with `{"type", "schema_version", "record"}`, dependency ordering, redaction modes with safe defaults (`--include-llm-traces=evidence-grade-only`, `--include-source-content=public-only`, `--include-pii=never`), `lms import --dry-run` and `--apply`.

### Finding 9 (`demo-001` — pre-registered demo protocol)
- `docs/product/project-plan.md` Minimum Demo Criterion — item 6 rewritten to reference the pre-registered protocol; default protocol shape added (8 items, 4 system-routed, 4 held-as-comparison, day-30 unaided free-recall).
- `docs/product/project-plan.md` Milestone 4 deliverables — added: pre-registered demo retention protocol document at `docs/handoff/demo-retention-protocol.md`, written and locked before any demo prompts are authored.
- `docs/product/project-plan.md` Milestone 4 acceptance criteria — Minimum-Demo line rewritten to reflect the protocol.

### Finding 10 (`llm-001` — LLM client wrapper interface)
- `docs/product/project-plan.md` LLM "Operational requirements" — new subsection "LLM client wrapper interface (v1)" specifying primary call signature, pre-call budget preflight, retries/timeouts, post-call token/cost accounting + trace-class metadata + PII redaction, structured-output validation, eval replay, per-provider adapters.

### Finding 11 (`research-001` — research-registry consistency)
- `docs/product/project-plan.md` Milestone 2 — rewritten (see Finding 1 pointer).
- `docs/product/project-plan.md` API Surface Sketch — `/research/*` deferred indefinitely with explicit comment.
- `docs/product/research-domain-model.md` — added v1 scope note at top of file explicitly stating the entities live as YAML files in Phase 1, not runtime DB tables.

### Finding 12 (`graph-001` — knowledge graph bootstrap path)
- `docs/product/project-plan.md` Knowledge Graph — new subsection "Knowledge Graph Bootstrap (v1)" specifying Markdown importer (Milestone 2), CSV importer (Milestone 2), LLM `authoring-assist` proposals (Milestone 4), human approval gate, audit log.

## Round-2 Output Format

Write the round-2 output to `docs/handoff/phase1-codex-round2-findings.json` with this schema:

```json
{
  "agent": "codex",
  "phase": "phase1-round2-verification",
  "generated_at": "<ISO timestamp>",
  "verifications": [
    {
      "finding_id": "<from round-1, e.g. scope-001>",
      "status": "resolved | partially-resolved | not-resolved | regressed",
      "summary": "<one-sentence>",
      "rationale": "<2-4 sentences with doc/line refs to the post-change content>",
      "design_refs": ["<file>:<section or line range>"],
      "follow_up_needed": "<if any, what remains; otherwise 'none'>"
    }
  ],
  "new_concerns": [
    {
      "finding_id": "<new short-id>",
      "category": "new-concern | push-back",
      "topic": "<topic>",
      "summary": "<one-sentence>",
      "rationale": "<2-5 sentences with doc refs>",
      "design_refs": ["<file>:<section>"],
      "implementation_impact": "<which milestone or schema this would touch>",
      "proposed_resolution": "<concrete>"
    }
  ],
  "overall_assessment": "<2-4 sentences: is the design now ready for Phase 2 (issue generation) — yes / no / conditional? If conditional, name the conditions.>"
}
```

The `verifications` array should have exactly 12 entries — one per round-1 finding. The `new_concerns` array is empty if the changes did not introduce any new issues; non-empty if they did. The `overall_assessment` should give a clear go / no-go / conditional verdict for Phase 2.

If a verification reads `partially-resolved`, name the remaining gap concretely. If `not-resolved`, name what would resolve it. If `regressed`, explain what got worse.

End of round-2 brief.
