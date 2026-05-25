# Codex Phase 2 Brief — Initial Issue Queue Generation

Status: Phase 2 of the parallel-agent design pattern. Codex is asked to generate the initial set of implementation issues for Milestones 0-4 against the design docs that converged through Phase 1.

## Context

You (Codex) completed two rounds of design review on the Learning Management System project:

- **Round 1** (`docs/handoff/phase1-codex-findings.json`): 12 findings across schema-trim consistency, source citation, evidence schema, mastery materialization, FSRS adapter, privacy, ownership enforcement, export contract, demo falsifiability, LLM wrapper, research-registry consistency, and graph bootstrap.
- **Round 2** (`docs/handoff/phase1-codex-round2-findings.json`): verified resolutions; 11 of 12 resolved cleanly, with `scope-001` partially-resolved and one new concern (`scope-002`) on the same issue — `/capability/*` API placement.

The capability-API issue was fixed in a fourth doc pass after round 2:

- `/capability/targets`, `/capability/estimates`, `/capability/gap-analyses` moved from the v1 API block to the Phase 2+ block.
- `Current Capability And Certification` section in `docs/product/project-plan.md` and Segment 5 in `docs/product/early-design-decisions.md` rewritten to explicitly place capability artifacts in **Milestone 5**, not Phase 1.

The design is now consistent. Your overall round-2 assessment was "Conditional go for Phase 2 collaborative issue generation. The remaining issue is a narrow scope hygiene mismatch rather than an architectural blocker." That cleanup is done.

This brief is the Phase 2 task.

## Task

Generate the initial set of GitHub issues for Milestones 0 through 4. The output is a queue that will be filed into the new repo (`stranske/learning-management-system`) once it is created. The repo will be created from `stranske/Template` and registered in the standard consumer-repo automation system, so issues need to conform to the agent-readable format used by the opener / keepalive / verifier loop.

Focus: **Milestones 0-4 only.** Milestones 5-8 will produce their own issues later from a similar collaborative pass when their entry conditions are clearer. Do not generate issues for them in this pass.

## Inputs

Read in this order:

1. `README.md` — project framing and resolved decisions (Milestone summaries).
2. `docs/README.md` — doc map.
3. `docs/product/project-plan.md` — design plan with full Milestone 0-4 deliverables and acceptance criteria; Phase 1 Minimum Core entity list; SourceReference, EvidenceRecord, SchedulerEvidenceAdapter, ownership-enforcement, export contract, LLM wrapper, demo retention protocol, and graph bootstrap subsections; First Backlog Sequence; Minimum Demo Criterion.
4. `docs/product/early-design-decisions.md` — segmented decision queue; especially Segments 2 (mastery), 7 (stack), 8 (sustainability), 9 (privacy), 10 (LLM cost/routing).
5. `docs/product/development-testing-surfaces.md` — Design Defaults and Surfaces 1, 2, 5, 6.
6. `docs/product/research-domain-model.md` — v1 scope note at top; conceptual schema for YAML files.
7. `Workflows/templates/consumer-repo/docs/AGENT_ISSUE_FORMAT.md` (in the parent workspace at `/Users/teacher/Library/CloudStorage/Dropbox/Learning/Code/Workflows/templates/consumer-repo/docs/AGENT_ISSUE_FORMAT.md`) — the canonical issue body format used by the keepalive automation.

## Issue requirements

Each issue must be:

- **AGENT_ISSUE_FORMAT-conformant**: Why / Scope / Non-Goals / Tasks (checkboxes) / Acceptance Criteria (checkboxes) / Implementation Notes.
- **Self-contained**: a fresh agent picking up the issue cold should be able to act on it without reading the entire design corpus. Include file paths, module names, function/class names where reasonable, and the specific Implementation Notes pointer to the relevant design-doc section(s).
- **Specific**: tasks start with verbs; criteria are verifiable; no "improve the system" or "make it good." Test names mentioned where relevant. Concrete acceptance evidence (a passing test, an endpoint returning a specific shape, a file existing at a specific path).
- **Sized for the keepalive loop**: an issue should be completable by a single agent (opener → keepalive → closer) in roughly 1-3 push cycles. If a deliverable spans multiple weeks of work, split it into multiple issues with explicit `depends_on` ordering.
- **Sequenced** toward the Minimum Demo Criterion at Milestone 4 end. Every Milestone 0-4 issue should be either on the critical path to the demo or directly enabling something that is.

## Sizing target

Aim for **25-35 issues total** across Milestones 0-4. Rough per-milestone shape (adjust as the design suggests):

- **M0** — repo and decision foundation: ~3-5 issues (Workflows template setup, secrets registration, stack decision record, initial architecture docs, opener/closer registry updates).
- **M1** — backend skeleton: ~4-6 issues (FastAPI app skeleton, Postgres + Alembic, pytest + ruff + black + mypy, CI plumbing, health endpoint, auth placeholder).
- **M2** — research registry (YAML) + SourceReference + importers: ~5-7 issues (YAML schemas + validator, SourceReference entity + CRUD + drift detection, Markdown importer, CSV importer, audit log).
- **M3** — knowledge graph + evidence + Inspect + export: ~6-9 issues (KnowledgeNode + KnowledgeEdge with ownership_scope, Prompt with provenance, Attempt, EvidenceRecord verbose schema, MasteryEstimate computed view, FSRS-4.5 placeholder library integration, Inspect surface, export/import contract, ownership-boundary tests).
- **M4** — retrieval + review queue + LLM study loop: ~7-10 issues (FSRS adapter rule table, daily cap + pause/vacation, stale-item handling, study-coach + practice modes, LLM client wrapper with budget kill-switch, cost monitoring, trace classification + local redaction, eval gold set, formative interaction policy, learner nudge controls, demo retention protocol doc).

These are sketches; the design docs are the authority on what work needs doing.

## Labels

Suggested labels per issue (Codex picks based on sequencing and risk):

- `priority:high` / `priority:normal` / `priority:low` — opener uses these to pick work. Most M0-M2 should be `priority:high`; some M3-M4 are `priority:normal`.
- `repo-review-approved` — the initial queue came from this collaborative review process; apply to every issue in this batch.
- `milestone:M0` / `milestone:M1` / `milestone:M2` / `milestone:M3` / `milestone:M4` — milestone tags for filtering.
- Other labels are out of scope for this pass (the consumer-repo template installs a label inventory at repo creation; don't try to anticipate them all).

## Dependency sequencing

Use `depends_on` to express ordering. Examples:

- The FastAPI app skeleton (M1) depends on the stack decision record (M0).
- Alembic migrations depend on the FastAPI app skeleton.
- The SourceReference CRUD depends on the FastAPI app skeleton and on the migration framework.
- The Markdown importer depends on SourceReference CRUD and on KnowledgeNode (because it creates draft nodes with source links).

A roughly linear chain is fine for M0-M2; M3 and M4 have more parallelism. Issues with no `depends_on` (empty array) are eligible to start as soon as the repo is created.

## Output schema

Write the output to `docs/handoff/phase2-codex-issue-candidates.json` with this shape:

```json
{
  "agent": "codex",
  "phase": "phase2-issue-generation",
  "generated_at": "<ISO timestamp>",
  "scope": "milestones-0-through-4",
  "issues": [
    {
      "issue_id": "M0-001",
      "milestone": "M0",
      "title": "<short imperative, under 70 chars>",
      "labels": ["priority:high", "repo-review-approved", "milestone:M0"],
      "depends_on": [],
      "body_markdown": "## Why\n\n<...>\n\n## Scope\n\n<...>\n\n## Non-Goals\n\n<...>\n\n## Tasks\n\n- [ ] <...>\n- [ ] <...>\n\n## Acceptance Criteria\n\n- [ ] <...>\n- [ ] <...>\n\n## Implementation Notes\n\n<...>"
    }
  ],
  "sequencing_notes": "<2-5 sentences: how the issues sequence toward the Minimum Demo, where parallelism is possible, any critical dependencies that gate a phase>",
  "overall_assessment": "<2-4 sentences: is this queue ready to file once the repo exists, or are there gaps Codex flags for the project owner to resolve first?>"
}
```

Notes on the schema:

- `body_markdown` is a single string containing the full AGENT_ISSUE_FORMAT body (with embedded newlines `\n`, valid JSON). The issue title is in the `title` field, not in the body. A consumer can directly `gh issue create --body "<body_markdown>"` if the JSON is unescaped properly.
- `issue_id` is `M<milestone>-<NNN>` (zero-padded within the milestone, e.g., `M3-007`). Stable across the file.
- `depends_on` references other `issue_id` values in this same file.
- `labels` includes the priority, the `repo-review-approved` tag, and the milestone tag at minimum.

## Conventions for body content

For **Why**: 1-3 sentences. Refer to the learning-science motivation and the design-doc section. Example: "The system thesis requires evidence as a first-class entity (see docs/product/project-plan.md Mastery section); without the verbose EvidenceRecord schema, future learned-model fitting is forced to learn artifacts of the schema rather than learner state."

For **Scope**: bullet list of what the issue covers. Bounded; references specific files/modules.

For **Non-Goals**: explicit exclusions to prevent scope creep. Especially important for issues whose neighbors might overlap.

For **Tasks**: 3-8 checkbox items, each actionable. Include test-writing tasks. Example: `- [ ] Implement \`src/lms/evidence/models.py:EvidenceRecord\` SQLAlchemy model with verbose schema fields`.

For **Acceptance Criteria**: 3-6 verifiable conditions. Each is independently checkable. Example: `- [ ] \`tests/evidence/test_models.py::test_evidence_record_roundtrip\` passes` or `- [ ] \`alembic upgrade head\` succeeds on a fresh DB and creates an \`evidence_records\` table with all schema columns`.

For **Implementation Notes**: one paragraph (or short bulleted list). Cite the design-doc section by path and heading. Optionally include hints on libraries to use (e.g., FSRS-4.5 from `py-fsrs`), key gotchas, or trade-offs to consider.

## Out of scope for this pass

- Milestones 5-8 issues (analyst training, public education, accessibility pilot, etc.) — generated later, separately.
- Issue labels beyond priority / repo-review-approved / milestone tags — the consumer template's label inventory installs at repo creation; do not pre-invent labels.
- GitHub project board organization — the user manages that after the issues are filed.
- Time estimates — the keepalive loop's own rhythm is the relevant measure, not calendar dates.

## Quality bar

Before completing, sanity-check the queue against these:

1. **Every Minimum Demo Criterion requirement is covered by issues.** Look at the 6 demo capabilities and trace each one to issue(s) that produce it.
2. **Every Phase 1 Minimum Core entity has an issue.** All 11 entities (User, Learner, KnowledgeNode, KnowledgeEdge, SourceReference, Prompt, Attempt, EvidenceRecord, ReviewQueueItem, LearningGoal, LLMSession) appear in at least one Tasks list.
3. **Dependencies form a DAG.** No cycles; every issue's `depends_on` references existing `issue_id` values.
4. **No orphan issues.** Every issue contributes to either the Minimum Demo Criterion or a Milestone acceptance criterion. If you can't say why an issue is on the path, it doesn't belong.
5. **No double-counted issues.** Each entity's primary creation lives in one milestone; later milestones extend rather than recreate.

End of Phase 2 brief.
