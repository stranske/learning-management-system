# Phase 3 Convergence Report — M5 + M6 Issue Queue

Status: Codex Phase 3 generation complete (`docs/handoff/phase3-codex-issue-candidates.json`); Claude review below for project owner adjudication before filing.

## Summary

**32 issues generated** across Milestones 5 and 6 (M5: 19 | M6: 13), within the 25-35 target.

**Structural validation — all pass:**

- JSON parses; 32 unique `issue_id` values.
- 0 unresolved `depends_on` references.
- DAG is acyclic (verified via standard cycle-detection).
- Priority distribution: 14 high / 17 normal / 1 low. M5 entity foundations and gap-closing artifacts are `priority:high`; UI surfaces mostly `priority:normal`; M5-018 research-registry YAML extension is the lone `priority:low`.
- All 30 M5 entities from the brief's table are covered (each mentioned in 2-15 issues — `Rubric` at 15, `FeedbackRecord` at 9, niche entities like `RemediationTrigger` and `EvidencePacket` at 2 each).
- **No deferred-scope leakage detected.** Heuristic check for `Course`, `Module`, `Lesson`, `CertificationSnapshot`, `Scenario` (excluding `Case`-subset), `Coach*`, `PublicLearningProgram` in `Tasks` sections found zero issues introducing these as new entities.
- AGENT_ISSUE_FORMAT bodies look well-formed across the sample.

**Codex's overall assessment:** *"This queue is ready to file as an implementation batch for Milestones 5 and 6. The main owner-facing decisions left inside the issues are narrow implementation choices: whether `KnowledgeProfile` is persisted or computed, whether Pico or Tailwind is selected for the prototype shell, and how rich the first screenshot workflow should be. Deferred institutional certification, full simulation, coaching workflow, curriculum containers, and public-learning artifacts are explicitly excluded."*

**Claude's overall assessment:** Agree. The queue is materially ready to file. The three owner-facing decisions Codex flagged are real but small — the issue bodies leave them open for the implementer rather than forcing a wrong default. Three more observations below for your awareness; none block filing.

## Items needing your input (Codex's three + my additional observations)

### A. M5-001 — `KnowledgeProfile`: persist or compute?

**The question:** Should `KnowledgeProfile` be a SQLAlchemy table that gets written on attempt/evidence updates, or a service-computed view (like `MasteryEstimate`)?

**How Codex handled it:** Issue body says *"Add `KnowledgeProfile` as a sibling to `Learner` in `src/lms/learners/models.py` **or** as a computed/service-backed model under `src/lms/learners/` if persistence is not needed yet."* Acceptance criteria insist the implementation **reads existing `EvidenceRecord` rows and does not introduce a persisted `MasteryEstimate` table** — so the MasteryEstimate-as-computed-view discipline is preserved regardless.

**My recommendation:** Leave it open; the implementer should pick based on Inspect-surface latency once they wire it up. Computed is the safer Phase-1-aligned default; persisted with `estimator_version` + `generated_at` is the right escape hatch if the demo reveals scheduler reads getting slow. The acceptance criteria already prevent the bad outcome (silently introducing a written mastery table), so the choice is genuinely flexible.

**Need from you:** Confirm "leave open" (recommended) or pre-pick persisted-vs-computed.

### B. M6-001 — Pico or Tailwind for the prototype shell?

**The question:** Which responsive CSS framework should anchor the M6 web prototype?

**How Codex handled it:** Issue body says *"Document the CSS framework choice in `docs/development/web-prototype.md`; default to Pico or Tailwind with a concrete rationale."* The first task is "Choose and document the CSS framework and route naming convention."

**My recommendation:** **Pico.** It's classless / semantic-first, zero build step, and produces clean HTML that survives screenshot tests easily. Tailwind needs Node + a build pipeline + utility-class proliferation that fights with FastAPI-rendered templates. For a prototype scoped at "make Phase 1 design surfaces inspectable on mobile," Pico is materially less yak-shave for the same visual outcome. If a richer design system becomes necessary later (e.g., the public pension education path in M8), the framework choice can revisit.

**Need from you:** Pico (recommended), Tailwind, or "leave open"?

### C. M6-012 — Screenshot mechanism: HTML snapshots vs Playwright?

**The question:** How to generate the mobile-width documentation screenshots for each M6 surface.

**How Codex handled it:** Issue body says *"Use FastAPI TestClient HTML snapshots **or** Playwright only if already available/added intentionally as a dev dependency."* Non-Goals include *"Adding a brittle full visual-regression platform"* and *"Requiring external browser services in CI."*

**My recommendation:** Start with **rendered-HTML snapshots** committed as `.html` files (or rendered to PNG locally if a tiny headless-rendering library is justified — `wkhtmltopdf` or `weasyprint` already in the Python ecosystem). Playwright adds Node, browser binaries, and CI overhead disproportionate to what's actually being documented at this stage. The acceptance criterion *"No screenshot requires live external network access or real LLM provider credentials"* already rules out the brittle path.

**Need from you:** HTML snapshots (recommended), local headless-render to PNG, or full Playwright?

## Other observations (no action required unless something looks wrong)

### D. M5-019 has 17 `depends_on` entries

The export/import contract extension depends on every other M5 entity issue. That's correct — export schema needs to know about each entity it serializes. Side effect: the export work will sit waiting until every M5 entity lands. It could be split into per-domain export extensions (feedback export, rubric export, capability export, etc.), but Codex chose to batch. Acceptable given the alternative is many small parallel PRs each touching the same `export_import.py` module (merge-conflict prone).

### E. M6-012 and M6-013 are heavy late-stage dependencies

M6-012 (screenshot tests) depends on 10 M6 surface issues; M6-013 (acceptance gate test) depends on 11. These will sit waiting through most of the M6 work, then land at the end. Expected and correct sequencing for an end-to-end gate.

### F. A few issues are entity-cluster batches

- **M5-002:** ReviewPolicy + ReviewSchedule + SchedulerDecision in one issue (three entities).
- **M5-016:** Case + CaseStep + DecisionPoint + EvidencePacket in one issue (four entities).

Both are reasonable groupings — the entities are tightly coupled and would create churn if split. Given the verifier-follow-up pattern we observed in Phase 2 (most issues take 2 PR cycles), these batches are sized appropriately.

### G. Anti-pattern guardrails are consistently present

I checked random samples for the language hygiene the design committed to:

- "Nonpunitive gap language" — explicit in M5-013 acceptance criteria.
- "No fixed ability labels / no shame language" — explicit in M5-005, M5-007 (low rubric score → feedback action, not learner label), M6-004 (dashboard copy).
- "Personal-scope only" for capability artifacts — explicit in M5-011 (rejects institutional scope at the API), M6-010 (institutional controls absent or disabled in UI).
- "Cross-scope normal edges cannot be created from UI" — explicit in M6-002 and M6-009.
- "Uncited LLM claims flagged `unverified`" — explicit in M6-008.
- "Local-only source content excluded from default export" — explicit in M5-019 redaction defaults; explicit in M6-006 attempt-flow UI (local-only locators hidden).

Consistent with the design corpus.

### H. Tests routed correctly per Phase-1 retrospective

The brief noted that PR #80 had to re-host sustainability tests. Several Phase 3 issues call out test directory explicitly:

- M5-001: *"`tests/learners/test_knowledge_profile.py`, not under `tests/integration/`"*
- M5-005: *"document the test location as `tests/feedback/test_feedback_templates.py`, not `tests/integration/`"*
- M5-007: *"add tests at `tests/feedback/test_rubric_scoring.py`, not under `tests/integration/`"*

Codex absorbed the lesson. Good.

### I. Migration path explicit where it matters

M5-004 (FeedbackRecord promotion) keeps backward compatibility with the existing `Attempt.feedback` field rather than removing it. M5-002 names the migration anchor (*"after `20260525_0013_llm_learner_controls.py`"*). M5-018 (ResearchScan/EvidenceReview as YAML) explicitly tests that **no SQLAlchemy model is added under `src/lms/`** and **no `/research` route appears in OpenAPI**. These are exactly the migration-safety checks that prevent later refactoring pain.

## Coverage matrix

**M5 entities:** All 30 from the brief table are covered. ✓

**M6 surfaces:** All 7 development-testing-surfaces.md surfaces in M6 scope have dedicated issues (M6-002/003 → Surface 3; M6-004 → Surface 1; M6-005 → Surface 6; M6-006 → Surface 1 attempt-flow; M6-007 → Surface 1 feedback view; M6-008 → Surface 2; M6-009 → Surface 4; M6-010 → Surface 7; M6-011 → Surface 8). ✓

**Acceptance gate:** M6-013 explicitly maps the gate to "author Goal + Node + Prompt + Rubric + Case set; learner completes prompts; rubric-scored feedback; capability/gap analysis; maintenance-plan steps." Matches the adapted-for-Phase-1-trim gate definition from the brief. ✓

**Export contract:** M5-019 covers every new M5 entity with explicit redaction defaults (inferred capability commentary excluded by default; formative/ephemeral LLM feedback event bodies excluded by default; local-only evidence packet content excluded). ✓

## What I need from you

1. **Items A, B, C** above — confirm defaults (recommended) or pick alternatives:
   - A. KnowledgeProfile: leave persistence call open (Rec) / pre-pick persisted / pre-pick computed
   - B. CSS framework: **Pico** (Rec) / Tailwind / leave open
   - C. Screenshot mechanism: **HTML snapshots** (Rec) / local headless-render / full Playwright

2. **Anything else** in the 32 issues that looks off, missing, or mis-scoped? The full queue is at `docs/handoff/phase3-codex-issue-candidates.json`. The 19 M5 issue titles are visible in `sequencing_notes`; M6 titles span the 13 UI surfaces plus screenshot tests plus the gate.

## After adjudication

Once you've given me direction on items A/B/C (or said "go with recommendations"), I'll:

1. Apply any issue body edits per your adjudication (small edits to M5-001, M6-001, M6-012 to bake in the choices).
2. Skip the optional round-2 Codex verification (consistent with Phase 2 pattern after mechanical edits).
3. File the 32 issues to `stranske/learning-management-system` via `gh issue create`, persisting an `issue_id → issue number` mapping at `docs/handoff/phase3-issue-number-mapping.json` (same pattern as Phase 2).
4. Commit the briefs / convergence report / candidates JSON / mapping into the repo via a docs-only PR (Gate should pass quickly on docs-only changes).

Then the opener fleet picks them up and the same keepalive/verifier cycle that worked for the Phase 2 31 issues runs on the next 32.
