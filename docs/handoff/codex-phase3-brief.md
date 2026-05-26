# Codex Phase 3 Brief — M5 + M6 Issue Queue Generation

Status: Phase 3 issue-generation pass. Same collaborative pattern as Phase 2 (\`codex-phase2-brief.md\`), now generating implementation issues for Milestones 5 and 6 on top of the now-substantially-complete Phase 1 (Milestones 0-4) implementation.

## Context

You (Codex) generated the Phase 2 issue queue (31 issues for M0-M4) on 2026-05-25 against \`codex-phase2-brief.md\`. That queue was filed as issues #1 through #31. Status today (2026-05-26):

- **M0:** 4 / 4 closed ✓
- **M1:** 4 / 4 closed ✓
- **M2:** 6 / 6 closed ✓
- **M3:** 6 / 7 closed (issue #20 "Build Inspect surface backend and UI shell" deliberately held open by closer policy; PR #86 is the verifier-follow-up adding ownership-scope tests, currently OPEN and CLEAN)
- **M4:** 10 / 10 closed ✓
- Demo retention protocol + coverage matrix documents both exist in \`docs/handoff/\` and the project owner plans to start the day-30 retention demo within the next 24 hours.

A substantial \`src/lms/\` implementation now exists: \`analytics/\`, \`api/\` (with \`health.py\`, \`inspect.py\`, \`audit.py\`), \`audit/\`, \`auth/\`, \`curriculum/\` (placeholder), \`db/\`, \`demo.py\`, \`evidence/\`, \`export_import.py\`, \`feedback/\` (placeholder), \`graphs/\`, \`importers/\`, \`learners/\`, with the typical \`models.py\` / \`schemas.py\` / \`repository.py\` / \`api.py\` split per module. **Codex must read the actual current source to ground M5/M6 issue bodies in real file paths and module structure rather than relying solely on the design docs.**

Two Workflows-side fixes landed yesterday that resolve the bootstrap pain we hit on the first PR (Workflows#2157 — \`ci.yml\` \`pull_request:\` trigger removed, guard allowlist for legacy orchestrator, SETUP_CHECKLIST §3.3.1 documenting \`default_workflow_permissions=write\`; Template#745 — one-shot canonical refresh). Fresh PRs no longer need the workarounds the Phase 2 PRs needed.

## Task

Generate the implementation issues for **Milestone 5** (Feedback, Rubrics, Transfer Cases + Personal Gap-Closing) and **Milestone 6** (Authoring and Learner Web Prototype). Output is a queue ready to file as GitHub issues in \`stranske/learning-management-system\`.

**Focus: M5 and M6 only.** Milestones 7 (analyst training pilot) and 8 (public education + accessibility pilots) will be planned in a later wave once M5/M6 and the day-30 demo reveal what should shape them. Do not generate issues for M7 or M8 in this pass.

## Inputs

Read in this order:

1. \`README.md\` — project framing, repo + design decisions snapshot.
2. \`docs/README.md\` — doc map.
3. \`docs/product/project-plan.md\` — especially "Mastery Is An Evidence-Backed Estimate" (already implemented), "Phase 1 Minimum Core" (already implemented; should not be re-implemented), **"Phase 2 Adaptive Learning Core"** (the entity set M5 should add), Milestone 5 and Milestone 6 sections under Implementation Roadmap, "Current Capability And Certification" (personal-scope artifacts in M5; institutional artifacts deferred), Feedback And Rubric System section, Scenario And Simulation Layer section (M5 takes the *case*-related subset; the full simulation layer is M7+).
4. \`docs/product/early-design-decisions.md\` — Segment 5 (capability/gap-closing in M5, not Phase 1), Segment 8 (sustainability — relevant for ReviewSchedule), Segment 9 (privacy — relevant for LLMFeedbackEvent retention), Segment 10 (LLM cost — relevant for new LLM-driven features in M5).
5. \`docs/product/development-testing-surfaces.md\` — all surfaces; M6 builds out Surfaces 1, 3, 4, 5, 6, 7, 8 (Learner Loop, Authoring, Knowledge Graph, Inspect, Review Queue, Capability/Gap, Coach/Manager). Surface 2 (LLM Study) already exists from M4.
6. \`docs/product/research-domain-model.md\` — \`Rubric\`, \`OutcomeMeasure\` schemas hint at M5 entities; the YAML-only research registry continues.
7. \`docs/handoff/phase2-codex-issue-candidates.json\` — the Phase 2 queue for shape/style reference. Each M5/M6 issue should match the same \`body_markdown\` quality, AGENT_ISSUE_FORMAT conformance, and self-containment.
8. \`docs/handoff/phase2-convergence-report.md\` — what was adjudicated last time, including the Phase 1 vs Phase 2+ boundary decisions (capability endpoints are Phase 2+, etc.).
9. \`Workflows/templates/consumer-repo/docs/AGENT_ISSUE_FORMAT.md\` at the parent workspace — canonical body format.

**Crucially, also read the actual implementation:**

10. \`src/lms/\` — walk the tree. Confirm what's already in place before specifying anything that would duplicate it. Pay special attention to:
    - \`src/lms/evidence/models.py\` — current \`EvidenceRecord\` schema (verbose, per Phase 1). M5 should add to it, not redefine.
    - \`src/lms/evidence/api.py\` — current Attempt + feedback (structured field) handling. M5 promotes feedback to its own table.
    - \`src/lms/graphs/models.py\` — current KnowledgeNode/Edge with \`ownership_scope\`. M5's ReviewSchedule and gap-analysis will join against this.
    - \`src/lms/feedback/\` directory — currently a placeholder; M5 lands the substantive content here.
    - \`src/lms/learners/models.py\` — current Learner + LearningGoal. M5 adds KnowledgeProfile as a sibling.
    - \`src/lms/api/inspect.py\` — the current Inspect surface (which M6's full UI will extend).
    - \`src/lms/export_import.py\` — the current export contract. M5 entities must be included in the export schema (with appropriate redaction defaults per Segment 9).

## Milestone 5 Scope

**Entities to add (per "Phase 2 Adaptive Learning Core" in project-plan.md):**

| Entity | Where it lands |
|---|---|
| \`KnowledgeProfile\` | \`src/lms/learners/models.py\` (sibling to \`Learner\`) or new \`src/lms/profile/\` module — Codex's call |
| \`ReviewSchedule\` | \`src/lms/scheduling/models.py\` if a scheduling module exists, otherwise create it; refines what Phase 1's \`ReviewQueueItem\` does with explicit schedule records and reason codes that survive the queue item |
| \`ReviewPolicy\` | sibling to \`ReviewSchedule\`; per-knowledge-type policy (e.g., factual vs procedural vs transfer) that the SchedulerEvidenceAdapter consumes |
| \`SchedulerDecision\` | sibling; records *why* the scheduler picked each task (Inspect surface already reads from this conceptually) |
| \`RemediationTrigger\` | sibling; rules from the design (failed prerequisite → schedule remediation, etc.) |
| \`MisconceptionPattern\` | \`src/lms/feedback/models.py\` or \`src/lms/graphs/models.py\` — Codex's call; pattern catalog the feedback system can map specific wrong-answer signatures to |
| \`FeedbackRecord\` | promote from the current \`Attempt\`-field representation into its own table in \`src/lms/feedback/models.py\` |
| \`FeedbackTemplate\` | \`src/lms/feedback/models.py\`; reusable feedback templates with placeholders |
| \`FeedbackAction\` | \`src/lms/feedback/models.py\`; the next-action a feedback record specifies (retry / parallel-prompt / prerequisite-remediation / model-comparison / revision / coach-review / author-review) |
| \`Rubric\` | \`src/lms/feedback/models.py\` |
| \`RubricCriterion\` | sibling |
| \`RubricScore\` | sibling; how an Attempt is scored against a Rubric |
| \`ModelAnswer\` | \`src/lms/feedback/models.py\`; the canonical answer for a Prompt (separate from \`SourceReference\` body) |
| \`Hint\` | \`src/lms/feedback/models.py\`; structured hints with reveal-tracking |
| \`RevisionRequest\` | \`src/lms/feedback/models.py\`; the request → revised-submission loop |
| \`Competency\` | \`src/lms/competencies/models.py\` (new module); observable role capability that nodes contribute to |
| \`CompetencyEvidence\` | sibling; many-to-many between Competency and EvidenceRecord |
| \`LearningInteractionSkill\` | \`src/lms/llm/models.py\`; named skills the LLM applies (study-coach, transfer, etc., currently config-only) — promoted to data |
| \`LLMFeedbackEvent\` | \`src/lms/llm/models.py\`; per-turn feedback events with trace-class and source citation, distinct from general \`LLMSession\` |
| \`CapabilityTarget\` | \`src/lms/capability/models.py\` (new module) — personal gap-closing |
| \`CapabilityEstimate\` | sibling; computed estimate against a target with confidence and evidence breakdown |
| \`GapAnalysis\` | sibling; compares estimate to target, produces gap-closing plan |
| \`MaintenancePlan\` | sibling; the gap-closing plan as actionable steps tied to scheduler |
| \`ResearchScan\` | YAML in \`docs/research/registry/\` plus a validator hook, NOT a runtime entity (consistent with Segment 9 / research-registry-as-YAML in Phase 1) |
| \`EvidenceReview\` | same — YAML + validator |

**Transfer-case subset (the part of "Scenario And Simulation Layer" that M5 needs):**

| Entity | Note |
|---|---|
| \`Case\` | \`src/lms/cases/models.py\` (new module); transfer-case shell with EvidencePacket and rubric link |
| \`CaseStep\` | sibling; ordered steps within a case |
| \`DecisionPoint\` | sibling; learner-choice nodes with branching |
| \`EvidencePacket\` | sibling; the source material a case presents to the learner |
| \`WorkProduct\` | sibling; the learner's submission (memo, decision rationale, classification) |

**Deferred from M5 (stay in M7+):**

- \`Scenario\` (full simulation envelope), \`SimulationRun\`, \`Debrief\` — wait for M7 analyst pilot.
- \`Coach\`, \`CoachAssignment\`, \`CoachIntervention\`, \`ManagerView\`, \`LearningContract\`, \`Notification\`, \`EscalationRule\` — Coaching And Accountability layer waits for M7.
- \`CertificationSnapshot\`, \`RecertificationPolicy\`, \`EvidenceDecayPolicy\` — institutional certification artifacts; defer indefinitely until institutional/evaluation scope enters (per Phase 1 / Phase 2 boundary).
- \`Course\`, \`Module\`, \`Lesson\` — still deferred until institutional curriculum authoring enters.
- \`LearningObjective\` as a separate entity — still folded into \`LearningGoal\`.
- Public/client education entities (\`PublicLearningProgram\`, \`ClientLearningPath\`, etc.) — M8.

**M5 functional deliverables (per project-plan.md Milestone 5):**

- Rubrics with criteria and scoring; rubric-based feedback can create revision/remediation tasks.
- Model answers and hints, with reveal tracking that feeds back into evidence (hint-use down-weights, per the existing EvidenceRecord schema).
- Feedback templates and structured feedback records (promoted from Attempt-field).
- Case records and work-product submission for transfer-case assessment.
- Competency progress tracking; competency evidence aggregates from EvidenceRecord matching the competency's node set.
- Capability target → capability estimate → gap analysis → maintenance plan loop. Personal-scope only (\`ownership_scope: personal\` on the target).
- Export contract extended to cover all new M5 entities, with redaction defaults appropriate for each (e.g., \`FeedbackRecord\` body included by default; \`CapabilityEstimate\` excluded by default if it includes inferred-mastery commentary; etc.).

**M5 API surface additions** (per the Phase 2+ block of project-plan.md API Surface Sketch):

- \`/feedback\` (FeedbackRecord CRUD/read)
- \`/feedback-templates\`, \`/feedback-actions\`
- \`/rubrics\`, \`/rubric-criteria\`, \`/rubric-scores\`
- \`/competencies\`, \`/competency-evidence\`
- \`/capability/targets\`, \`/capability/estimates\`, \`/capability/gap-analyses\`, \`/capability/maintenance-plans\` (personal scope only; reject institutional-scope requests)
- \`/cases\`, \`/cases/{caseId}/steps\`, \`/cases/{caseId}/work-products\`
- \`/learners/{learnerId}/knowledge-profile\` (computed view, similar to \`mastery-estimates\`)
- \`/review-schedules\`, \`/review-policies\`, \`/scheduler-decisions\` (read-only for now; scheduler service writes these)
- \`/llm/interaction-skills\`, \`/llm/feedback-events\`

## Milestone 6 Scope

M6 is **UI work**, building out the learner + author + coach surfaces. **No new entities.** Every M6 issue consumes entities from M1-M5.

**Per project-plan.md Milestone 6 deliverables (with the Phase 1 trim respected — no Course/Module/Lesson UI):**

| Surface | Notes |
|---|---|
| Author view for **learning goals**, **knowledge nodes/edges**, **prompts** | extends the M3 Inspect surface; lets the project owner author content via the UI rather than CLI importers |
| Author view for **rubrics**, **feedback templates**, **cases** | new M5 entities |
| Learner dashboard | goals, mastery summary, due reviews, next actions, recent evidence; mobile-friendly per Design Defaults |
| Review queue view | reads the M4 review queue + M5 ReviewSchedule with reason codes |
| Activity attempt flow | the actual prompt-attempt UI, replacing the current debug-only Inspect attempt path |
| Feedback view | post-attempt feedback presentation, hint reveal, model answer (if revealed) |
| LLM study session view | exists in some form from M4 (\`/llm/sessions\`); M6 polishes the UI |
| Graph design / testing view | KnowledgeNode/Edge editor with \`ownership_scope\` enforced; LLM-proposed drafts surfaced for approval (M4-009 path) |
| Capability / gap-analysis view | M5 entities surfaced for the personal-learning use case |
| Basic manager or coach dashboard where policy allows | personal-scope only at M6; institutional/firm scope still deferred |
| Basic admin view | user management, label/permission inspection, repo state |

**M6 deliverables include:**

- A consistent responsive CSS framework choice (deferred from Phase 1; M6 picks it). Defaults: Tailwind or Pico. Document the choice.
- PWA scaffolding (manifest, service worker placeholder) — actual offline behavior is later, but the manifest + icons + install prompt land here.
- Routing convention (e.g., \`/app/learner\`, \`/app/author\`, \`/app/coach\`) consistent with the FastAPI mount points.
- Empty-state design for each surface (the demo will have very few records; empty states matter).
- Mobile-width screenshot tests (one per surface) as documentation artifacts in \`docs/screenshots/\`.

**M6 acceptance gate** (per project-plan.md): "a user can author a small course and another user can complete it." Adapting to the trimmed Phase 1: a user can author a small set of \`LearningGoal\` + \`KnowledgeNode\` + \`Prompt\` + \`Rubric\` and another user (or the same user as learner) can complete the prompts, see rubric-scored feedback, view capability/gap-analysis, and request maintenance-plan steps.

## Issue Requirements (same as Phase 2)

Each issue must be:

- **AGENT_ISSUE_FORMAT-conformant**: Why / Scope / Non-Goals / Tasks (checkboxes) / Acceptance Criteria (checkboxes) / Implementation Notes.
- **Self-contained**: a fresh agent should be able to act without reading the entire design corpus. Include current file paths from the actual \`src/lms/\` tree.
- **Specific**: tasks start with verbs; criteria are verifiable; concrete acceptance evidence (test names, endpoint shapes, file existence at specific paths).
- **Sized for 1-3 keepalive push cycles**.
- **Sequenced** via \`depends_on\` toward the M6 acceptance gate.

**Honest about the verifier follow-up pattern** (observed from Phase 2 work):

The keepalive runner often produces a first PR that the verifier flags, requiring a follow-up PR to address the verifier's concerns. M5/M6 issues should anticipate this — bodies do *not* need to call out the follow-up cycle explicitly (the closer/verifier infrastructure handles it), but **sizing should assume one round-trip per issue, not one PR per issue**. Acceptance criteria should focus on *what verifier-PASS evidence looks like*, not just "code works."

**Tests sometimes need re-hosting** (PR #80 pattern): when an issue spans multiple modules, explicitly note the test directory layout (e.g., "tests live at \`tests/feedback/test_rubric_scoring.py\`, NOT at \`tests/integration/...\`").

## Sizing Target

Aim for **25-35 issues total** across M5 + M6. Rough breakdown:

- **M5 entity + service work:** ~12-18 issues (one or two entities per issue grouped by domain — feedback group, rubric group, case group, capability group, scheduler refinements group, competency group, LLM-event group, research-registry YAML extensions).
- **M6 UI work:** ~10-15 issues (one per surface, plus the CSS framework + PWA scaffolding setup issue, plus an M6 acceptance-gate end-to-end test issue).

This is comparable to Phase 2's 31. Don't bloat — sub-issues that fit naturally together as a single PR should be one issue.

## Labels

Same scheme as Phase 2:

- \`priority:high\` / \`priority:normal\` / \`priority:low\`. M5 entity foundations (FeedbackRecord, Rubric, CapabilityTarget, KnowledgeProfile) → high. M6 individual surfaces → normal (the foundational PWA-setup issue is high).
- \`repo-review-approved\` — all issues in this batch.
- \`milestone:M5\` / \`milestone:M6\` — milestone tags.

No new labels beyond the existing inventory.

## Dependency Sequencing

Use \`depends_on\` to express the natural DAG:

- M5 entity-creation issues (models + migrations) come before M5 service/API issues.
- M5 \`FeedbackRecord\` table promotion depends on the M4 \`Attempt\`-with-structured-feedback-field issue (already closed; no \`depends_on\` needed for the queue but Implementation Notes should reference the migration path).
- M5 \`Rubric\` precedes M5 \`RubricScore\`.
- M5 \`CapabilityTarget\` precedes \`CapabilityEstimate\` precedes \`GapAnalysis\` precedes \`MaintenancePlan\`.
- M5 \`Case\` precedes \`WorkProduct\` and \`DecisionPoint\`.
- M6 CSS-framework + PWA setup precedes individual M6 UI surfaces.
- M6 each surface depends on the relevant M5 entity issue (e.g., the rubric authoring UI depends on \`Rubric\` model landing).
- M6 acceptance-gate end-to-end test depends on all M6 surface issues.

## Output Schema

Write the output to \`docs/handoff/phase3-codex-issue-candidates.json\` with the same shape as Phase 2:

\`\`\`json
{
  "agent": "codex",
  "phase": "phase3-issue-generation",
  "generated_at": "<ISO timestamp>",
  "scope": "milestones-5-and-6",
  "issues": [
    {
      "issue_id": "M5-001",
      "milestone": "M5",
      "title": "<short imperative, under 70 chars>",
      "labels": ["priority:high", "repo-review-approved", "milestone:M5"],
      "depends_on": [],
      "body_markdown": "## Why\\n\\n<...>\\n\\n## Scope\\n\\n<...>\\n\\n## Non-Goals\\n\\n<...>\\n\\n## Tasks\\n\\n- [ ] <...>\\n\\n## Acceptance Criteria\\n\\n- [ ] <...>\\n\\n## Implementation Notes\\n\\n<...>"
    }
  ],
  "sequencing_notes": "<2-5 sentences: how the issues sequence through M5 entity foundations into M5 services into M6 UI, where parallelism is possible>",
  "overall_assessment": "<2-4 sentences: is this queue ready to file, or are there gaps the project owner should resolve first?>"
}
\`\`\`

\`issue_id\` is \`M5-NNN\` or \`M6-NNN\` (zero-padded within milestone). \`depends_on\` references other \`issue_id\` values in this same file. \`labels\` includes priority + \`repo-review-approved\` + milestone tag.

## Conventions

Same as Phase 2:

- **Why:** 1-3 sentences citing the learning-science motivation and the design-doc section.
- **Scope:** bullet list referencing specific files/modules in the current \`src/lms/\` tree.
- **Non-Goals:** explicit exclusions, especially M7+ scope that might tempt scope-creep (e.g., "this issue does NOT introduce \`CertificationSnapshot\` — that stays deferred").
- **Tasks:** 3-8 checkbox items, each actionable. Include test-writing tasks. Use real file paths.
- **Acceptance Criteria:** 3-6 verifiable conditions. Each independently checkable. Test names that match the actual existing pytest convention in \`tests/\`.
- **Implementation Notes:** one paragraph + citations to design-doc sections by path and heading; optionally references to relevant existing implementation files for migration paths.

## Quality Bar

Before completing, check:

1. **Every M5 entity in the table above is covered** by at least one issue's Tasks list. Walk the table; check for omissions.
2. **Every M6 surface listed above has its own issue** (or shares one with a closely related surface).
3. **Dependencies form a DAG**. No cycles; every \`depends_on\` references an \`issue_id\` in this file.
4. **No issues introduce deferred scope.** Search the queue for \`Course\`, \`Module\`, \`Lesson\`, \`CertificationSnapshot\`, \`Coach\`, \`Scenario\` (excluding \`Case\`/\`CaseStep\`), \`Simulation\`, \`PublicLearningProgram\` — these should NOT appear as new entities. References (e.g., "later \`Coach\` work will read this") are fine.
5. **The M6 acceptance gate is testable.** At least one issue produces the end-to-end test that proves "a user can author a small Goal+Node+Prompt+Rubric set and another user can complete it with feedback."
6. **Export contract is extended** for every new M5 entity (at least one issue covers this; not necessarily one per entity if grouped sensibly).
7. **Ownership-scope is honored** — every M5 entity that joins against KnowledgeGraph or Learner must declare its scope handling explicitly.

End of brief.
