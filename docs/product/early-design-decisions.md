# Early Design Decisions

Status: initial segmented decision queue.

This document breaks the early project decisions from [project-plan.md](project-plan.md) into manageable segments. Each segment should produce one or more decision records before implementation work begins.

## Decision Record Shape

Each decision should eventually be captured in this form:

```text
Decision:
Context:
Options considered:
Selected direction:
Reasoning:
Risks:
Follow-up questions:
Review date:
```

## Segment 1: First Product Boundary

Purpose:

- Decide what the first working version is trying to prove.

Questions:

1. Which initial use case should drive the first prototype?
   - personal learning from research notes;
   - new analyst training;
   - public pension client education;
   - company-wide onboarding;
   - dyslexic reading-learning design spike.
2. Who is the first real user: you, a small internal team, a public client, a student, or a course author?
3. What is the smallest useful learning loop for that user?
   - inspect content when needed;
   - perform an evidence-producing learner action;
   - retrieve, explain, apply, or revise;
   - receive formative feedback;
   - update current mastery estimate;
   - receive a next action;
   - return later through scheduled review or follow-up practice.
4. Should the first version be local/private, hosted personal, or institution-ready?
5. What should be explicitly out of scope for the first version?

Recommended default:

- Start with a local/private prototype for the project owner, using personal learning from research notes as the first concrete content path without narrowing the architecture to only that use case.
- Preserve the broader design for new analyst training, company-wide learning, public education, and dyslexic reading support while treating public/client education as a lower-priority pilot.
- Treat "learning loop" as the full cycle from task to evidence to feedback to learner-state update to next action. Content inspection alone is not a learning loop.
- Add a workable interface early enough to test real learning workflows.

Working Segment 1 decision:

```text
Decision: Build a local/primitive prototype first, with the project owner as the first real user.
Context: The system must ultimately support several use cases. Narrowing too aggressively around one use case would hide shared design needs across personal learning, analyst training, institutional learning, public education, and accessibility-sensitive learning.
Options considered: personal learning only; new analyst training first; public/client education first; dyslexic reading first; broad local prototype with one concrete starting content path.
Selected direction: Use personal learning from the collected research notes as the first concrete path, but design the core learning loop, graph, mastery, review, feedback, LLM, and UI structures broadly enough to carry the other major use cases forward.
Reasoning: The shared infrastructure is the important early work: learner action, evidence, feedback, current mastery, scheduled review, next action, graph structure, and formative interaction. These should not be overfit to one audience.
Risks: A broad design can become too abstract if the first prototype lacks a concrete content path. The first implementation must still ship a working loop.
Follow-up questions: Which research-note slice should seed the first prototype? Which UI surfaces are necessary to test the loop locally?
Review date: before Milestone 1 implementation.
```

Decision output:

- first audience;
- first curriculum slice;
- first user workflow;
- deployment assumption;
- explicit non-goals.

## Segment 2: Learning Model And Mastery

Purpose:

- Define what the system means by learning, mastery, current capability, and evidence.

Questions:

1. What evidence types should the system represent in version one, and what can each type legitimately tell us?
2. Should mastery require delayed retrieval from the beginning?
3. How should the system distinguish historical mastery from current mastery confidence?
4. What evidence should update a mastery estimate?
5. What should the system show a learner about uncertainty and forgetting?
6. What capability target should be used for the first gap-analysis workflow?

Recommended default:

- Model mastery as current, evidence-backed, time-sensitive confidence.
- Store historical mastery separately from current capability.
- Use delayed retrieval for any claim stronger than "same-session success."
- Treat evidence as multidimensional rather than binary: response quality, retrieval demand, support level, reference use, time since evidence, transfer distance, confidence, and human review all affect what the system can infer.
- Ship v1 with a deliberately simple placeholder mastery rule (FSRS-4.5 with default parameters) rather than reasoning from first principles. Treat the placeholder as throwaway scaffolding while data accumulates.
- Make `MasteryEstimate` a computed view over `EvidenceRecord` history, not a separately-written table, so changing the rule is a recompute rather than a migration.
- Treat the `EvidenceRecord` schema, not the mastery rule, as the load-bearing v1 decision. Log enough raw signal (timestamp, prompt id, prompt demand level, knowledge type, time since last attempt, response time, correctness, confidence rating, hint use, reference use, support level, retrieval demand, transfer distance, source-match quality) that a learned model can be fit later.
- Select the estimator function by knowledge type via a `MasteryEstimatorPolicy` resolved in code, not stored in the DB. Per-domain estimators are a later refinement, not a v1 schema commitment.
- Plan explicit empirical tuning around Milestone 6-7 once ~500-1000 evidence records exist on overlapping nodes, producing a written `MasteryModelV2` proposal grounded in observed data. Ship learned models behind a feature flag in shadow mode before switching.
- Keep the evidence model flexible so later development can add more granularity when the first representation proves too coarse.

Working Segment 2 decision:

```text
Decision: Represent mastery as a changing current-capability estimate computed from evidence, with the v1 update rule deliberately chosen as a throwaway placeholder while real data accumulates.
Context: The product should help learners and institutions understand what a learner appears to know and be able to do now, how that judgment was formed, how confident the system should be, and what should happen next. Calibrating a mastery rule from first principles before any evidence exists tends to produce elegant formulas that nobody trusts; calibrating from real attempts is more honest but requires running the system to generate the data.
Options considered: binary mastery; one fixed mastery threshold; delayed-retrieval-only mastery; multidimensional current mastery estimate from a hand-tuned rule; computed mastery view backed by a placeholder rule with explicit empirical refinement later.
Selected direction: Ship v1 with FSRS-4.5 (default parameters) as a per-node placeholder, with `MasteryEstimate` modeled as a computed view over `EvidenceRecord` history rather than a separately written table. Treat the `EvidenceRecord` schema as the load-bearing decision: log every field a future learned model could want. Resolve the estimator in code via a `MasteryEstimatorPolicy` keyed on knowledge type. Plan an empirical-tuning step around Milestone 6-7.
Reasoning: The mastery rule is the most likely thing to change in the first year. Designing the schema for retrofit-by-recompute keeps that option cheap, while a simple, transparent placeholder lets the system run honestly in the interim. Schema generality (uniform `EvidenceRecord` and `MasteryEstimate` across knowledge types) matters more than model generality (one formula for everything).
Risks: The placeholder may produce uninformative review cadence early. Cadence is partly downstream of how much the project owner actually uses the system; that question itself defers to Segment 8.
Follow-up questions: What exact fields belong in the first `EvidenceRecord`? What learner-facing labels should represent uncertainty without pretending to be precise? At what attempt-volume threshold does empirical tuning become viable for each knowledge type?
Review date: before implementing learner evidence and mastery estimate records; revisit after 500-1000 evidence records exist.
```

Decision output:

- first mastery rules;
- evidence types;
- current-capability language;
- gap-analysis target.

## Segment 3: LLM Learning Interaction

Purpose:

- Decide how LangChain/LangGraph-style interaction should support learning without undermining retrieval, assessment, or learner trust.

Questions:

1. What should the first LLM interaction mode be: study coach, exploration, practice, transfer, authoring assist, or assessment support?
2. Given the research findings, what default answer-versus-attempt policy should govern LLM learning sessions?
3. Given the research findings, what learner behaviors should the system treat as learning-risk signals that call for formative feedback?
4. How should learners reduce or disable feedback they experience as nagging?
5. Which assessment modes should disable hints, feedback, reference access, or LLM interaction?
6. Should LangSmith or an equivalent tracing/evaluation system be included in the first LLM prototype?
7. What traces, prompts, and sessions are sensitive enough to require special retention rules?

Recommended default:

- Begin with `study-coach` and `practice` modes.
- Use formative feedback by default, with learner-level controls and assessment-level overrides.
- Treat LLM outputs as draft or formative unless reviewed or validated.
- Build LangChain/LangGraph and LangSmith into the app as core infrastructure for LLM orchestration, tracing, evaluation, and prompt/session review.
- Monitor trace retention, privacy, assessment integrity, and sensitive-session handling as a major pre-implementation issue.

Research-derived interaction policy:

- The LLM should answer directly when the learner needs orientation, a concise explanation, confusion repair, accessibility support, or feedback after an attempt.
- The LLM should ask the learner to retrieve, predict, explain, compare, apply, or revise before answering when the session purpose is retrieval practice, transfer, current-capability evidence, durable learning, or remediation.
- The LLM should avoid turning every question into a quiz. The goal is productive learning, not friction for its own sake.
- The LLM should protect working memory by giving direct structure, examples, and scaffolds when the learner is overloaded or lacks prerequisites.
- The LLM should fade scaffolds when evidence suggests the learner can perform more independently.
- The LLM should treat answer-seeking during retrieval, repeated passive rereading, overuse of hints, premature reference use, rapid guessing, high confidence with weak evidence, repeated avoidance of attempts, and unsupported claims of understanding as learning-risk signals.
- Feedback on learning-risk behavior should be formative: name the learning goal, identify the observed behavior, explain the risk in learning-principle terms, and offer a next action.
- If the learner turns off the preferred formative approach, the system should briefly remind them why the approach exists, then honor the choice where policy allows.
- Summative assessments should be able to disable hints, feedback, reference access, and LLM interaction during the attempt while still supporting post-assessment feedback and gap-closing plans.

Working Segment 3 decision:

```text
Decision: Build LangChain/LangGraph and LangSmith as core LLM-learning infrastructure, governed by a research-derived formative interaction policy.
Context: LLM interaction should help learners deepen understanding, personalize sessions, practice retrieval, and transfer knowledge without becoming an answer vending machine or undermining assessment integrity.
Options considered: no LLM in early product; optional LLM later; unrestricted conversational LLM; core LLM layer with formative-learning policy and observability.
Selected direction: Start with `study-coach` and `practice` modes. Use LangChain/LangGraph for learning-session orchestration and LangSmith for tracing, prompt/session evaluation, datasets, and review. Use formative feedback by default, with learner controls and assessment overrides.
Reasoning: The research base favors retrieval, explanation, feedback, desirable difficulty, scaffolding, transfer, metacognitive calibration, and working-memory management. The LLM should implement those principles instead of merely answering questions. Observability is necessary because LLM learning interactions need evaluation and iteration.
Risks: Formative nudges can feel like nagging; privacy and retention rules for traces are not yet settled; LLM behavior can drift from the learning policy; assessment contexts require stricter controls.
Follow-up questions: What exact learner-facing control labels should be used for coaching intensity? What trace categories require restricted retention? What rubric should evaluate whether an LLM session stayed instructionally productive?
Review date: before implementing the first LLM study session.
```

Decision output:

- first LLM mode;
- formative feedback policy;
- learner controls;
- assessment restrictions;
- observability/evaluation choice.

## Segment 4: Knowledge Graphs

Purpose:

- Decide how institution-designed graphs and learner-authored graphs should coexist.

Questions:

1. Should the first graph be institutional, personal, or both?
2. What graph edge types are necessary in version one?
3. Who can publish or revise an institutional graph?
4. Should user performance generate graph-change proposals automatically or only reports for authors?
5. How much should LLM assistance be allowed in graph creation?
6. What review step is required before generated nodes or edges become official?

Recommended default:

- Start with manually reviewed graph drafts.
- Use personal/research-note graph implementation first while supporting both personal and institutional graph ownership in the model.
- Use prerequisite, supports-objective, supports-competency, related, contrast, transfer-context, and interference-risk edges in version one.
- Treat key-prerequisite, encompassing, and implicit-review-credit edges as later/experimental unless a specific implementation issue justifies them earlier.
- Let performance data create graph-improvement signals, not automatic graph changes.

Edge distinction:

- `prerequisite`: a node is generally useful or necessary before another node, but weakness may not fully block progress.
- `key-prerequisite`: a stronger claim that failure on the prerequisite is likely to prevent meaningful progress on the dependent node and should trigger blocking, remediation, or diagnostic priority.
- `interference-risk`: prior knowledge, a similar concept, or a misleading rule may cause confusion or negative transfer and should be tested through contrast, exception, or misconception-sensitive tasks.

Working Segment 4 decision:

```text
Decision: Build version-one graph support for personal and institutional graphs, starting with the project owner's personal/research-note graph while preserving institutional graph governance.
Context: Knowledge graphs are central to adaptive learning, prerequisite reasoning, transfer planning, review, and graph-improvement feedback. The graph should be useful without pretending to be a perfect map of knowledge.
Options considered: personal graph only; institutional graph only; both from the beginning; automatic graph revision from performance data; reviewed graph revision.
Selected direction: Support both graph ownership models. Implement personal/research-note graph use first. Version-one edge types are prerequisite, supports-objective, supports-competency, related, contrast, transfer-context, and interference-risk. Defer key-prerequisite, encompassing, and implicit-review-credit until the system has more evidence and scheduler maturity.
Reasoning: The first user needs a personal graph, but the architecture must support institution-authored content graphs later. Interference-risk belongs in version one because misconceptions, negative transfer, and easily confused concepts are central learning-design concerns. Key-prerequisite and implicit review are higher-confidence claims that should wait until evidence and scheduler behavior can support them.
Risks: Too many edge types can make authoring hard. The UI should expose simple defaults and let advanced edge meaning appear only when useful.
Follow-up questions: What graph visualization or adjacency view is sufficient for the first UI? What role names should govern institutional graph approval?
Review date: before implementing graph models and graph authoring UI.
```

Decision output:

- first graph type;
- allowed edge types;
- review workflow;
- performance-signal policy.

## Segment 5: Certification And Current Capability

Purpose:

- Define certification as a current capability estimate and improvement loop rather than a permanent label.

Questions:

1. What institutional question should certification answer?
2. What does "this person knows this right now" require as evidence?
3. How should confidence be expressed?
4. How should skill decay or forgetting be represented?
5. What should happen when current evidence falls below the target?
6. Which certification decisions require human review?

Recommended default:

- Implement `CapabilityTarget`, `CapabilityEstimate`, `GapAnalysis`, and `MaintenancePlan` in **Milestone 5**, after the Phase 1 Minimum Demo proves the core learner loop. They are explicitly **not** part of the Phase 1 / Milestones 0-4 scope. Gap-closing is the most actionable feature a personal learning system can offer: "I want to understand strategy X; the system tells me what evidence I'm missing and what to do next."
- Defer `CertificationSnapshot`, `RecertificationPolicy`, and `EvidenceDecayPolicy` until institutional or analyst-evaluation contexts enter scope. They are not needed when one learner is evaluating themselves and they add governance overhead the personal slice does not pay for.
- Pair every gap with a learning path.
- Avoid negative status language when evidence expires or weakens.
- Express current capability as a present-tense confidence judgment: what the learner appears able to do now, under what conditions, with what evidence and confidence.
- Require human review for professional judgment, high-stakes decisions, firm/client risk, public claims, accessibility-sensitive contexts, and summative institutional certification (when those contexts exist).

Working Segment 5 decision:

```text
Decision: Ship current-capability estimates and gap-closing artifacts in v1 for personal learning; defer certification-specific artifacts until institutional or evaluation contexts enter scope.
Context: Gap-closing is core to personal learning ("I want to understand strategy X; what should I do next?"). Certification language and permanence semantics are not needed when one learner is evaluating themselves; they add scope without serving the first user. The same evidence and mastery model serves both flows when institutional certification eventually lands.
Options considered: full certification stack in v1; current-capability only in v1; current-capability plus gap-closing in v1 with certification deferred; defer all of it until institutional use.
Selected direction: Ship `CapabilityTarget`, `CapabilityEstimate`, `GapAnalysis`, and `MaintenancePlan` in v1. Defer `CertificationSnapshot`, `RecertificationPolicy`, and decay-policy artifacts. Reuse the same evidence and mastery model for both flows when institutional certification lands.
Reasoning: Gap-closing makes the system actionable rather than informational. Certification permanence is a governance feature that does not pay off without an institution behind it. Splitting the two now avoids carrying certification overhead through the personal-learning slice.
Risks: Naming conventions can drift between personal gap-closing and institutional certification if not unified later. Some learners may still want a "completed" state for personal goals even without formal certification.
Follow-up questions: What confidence-tier labels should appear in the learner-facing gap-analysis UI? Which first capability target tests the gap-closing workflow on the project owner's personal learning slice?
Review date: before implementing capability/gap-analysis records.
```

Decision output:

- certification language;
- current-capability evidence rules;
- confidence display;
- gap-closing workflow.

## Segment 6: Public Education And Accessibility

Purpose:

- Keep the design broad enough for public-client education and dyslexia-sensitive reading instruction.

Questions:

1. What public pension topic should be the first client-education path?
2. What should the organization learn from aggregate client understanding?
3. What consent and privacy rules apply to public learners?
4. Which accessibility supports should be part of the base design rather than add-ons?
5. What does the dyslexic reading use case require that analyst training would not reveal?
6. What domain-specific research must be reviewed before building reading-intervention features?

Recommended default:

- Start public education with low-stakes understanding checks and aggregate misconception reporting.
- Treat dyslexic reading as a design stress test before implementation.
- Keep accessibility support separate from unsupported learning-style personalization.
- Make motivation and reward design explicit in the dyslexic reading stress test because persistence, frustration, feedback interpretation, and visible progress are central to whether the learning loop works.
- Prioritize domain-specific review of phonological awareness, decoding fluency, reading-comprehension assessment, and working-memory/cognitive-load design in reading.

Working Segment 6 decision:

```text
Decision: Treat public pension education as a later public-facing pilot and dyslexic reading as an accessibility and domain-specific design stress test.
Context: The system should not overfit to adult professional learning. Public education tests plain-language explanation and aggregate understanding feedback. Dyslexic reading tests fine-grained skill modeling, accessibility, motivation, reward design, pacing, and domain-specific evidence discipline.
Options considered: build public education early; ignore public education until later; treat dyslexic reading as an implementation target; use public/accessibility cases as architectural stress tests.
Selected direction: Public education will start later with low-stakes understanding checks and aggregate misconception reporting. Dyslexic reading will be used as a design stress test before implementation, with special attention to motivation, reward, phonological awareness, decoding fluency, reading-comprehension assessment, and working memory/cognitive load.
Reasoning: Public education is less urgent than the core learning engine but important for future product breadth. Dyslexic reading reveals design needs that analyst training may hide, including fine-grained graph structure, frustration-sensitive feedback, visible progress, accessibility defaults, and research review in a specialized domain.
Risks: Reading intervention is a high-specialization domain and should not be implemented from generic learning principles alone. Public pension education must avoid crossing into individualized financial advice unless separately governed.
Follow-up questions: Which public pension topic should be used for the later pilot? What reading-research review threshold is required before implementing dyslexic reading features? What motivation/reward patterns are evidence-aligned for struggling readers?
Review date: before public education pilot planning or reading-intervention implementation.
```

Decision output:

- first public education path;
- aggregate reporting policy;
- accessibility requirements;
- reading-domain research review needs.

## Segment 7: Stack, Governance, And Implementation

Purpose:

- Decide enough technical foundation to start building without overfitting the architecture too early.

Questions:

1. Backend stack: Python, TypeScript, or other?
2. Database: SQLite first, Postgres first, or both through a migration path?
3. API style: REST, GraphQL, or typed RPC?
4. Auth: local single-user, basic accounts, SSO-ready, or firm-grade from the start?
5. Should Workflows and GitHub issue automation be added immediately?
6. What data boundaries are mandatory from day one?
7. What UI surfaces are needed for early testing?

Recommended default:

- Use Python unless a later implementation issue reveals a strong TypeScript-specific reason.
- Use Postgres first, with local development configured around a primitive/local setup.
- Use REST plus OpenAPI first. GraphQL and typed RPC can be reconsidered when frontend complexity, graph querying, or client/server type-sharing creates a real need.
- Use FastAPI, SQLAlchemy, Alembic, Pydantic, and pytest as the starting backend stack.
- Include Jupyter and pandas in the project from the start. Empirical mastery-rule tuning, LLM cost/quality analysis, and evaluation set construction all happen most naturally in notebooks against the Postgres data.
- Use local auth first, but design the user/identity model so SSO can be added later.
- Use the Workflows consumer process from the beginning after repo initialization.
- Use a production-plausible data model even if the deployment is local and primitive.
- Design every UI surface mobile-friendly by default (PWA-ready). Pick a responsive CSS framework; avoid desktop-only interactions like hover-to-reveal. Native mobile is out of scope; a working PWA is on the roadmap.
- Route every LLM call through a single client wrapper. Model selection per mode is configured via env vars or a small config file so empirical model decisions are one-line changes rather than refactors.
- Ship per-mode LLM cost monitoring in v1 (daily log line of call count and dollar cost by mode) and a hard daily budget kill-switch with a low default.
- Build prompt provenance into the schema from day one. Every `Prompt` and `PromptVersion` records `authoring_method` (`human` / `llm-assisted` / `llm-generated`), `authoring_actor`, `reviewing_actor`, `approval_timestamp`, and (when applicable) `llm_model` and `prompt_template_version`. Cheap in v1, hard to retrofit.
- Add an audit log on authoring actions (actor + timestamp on every create/update of nodes, edges, prompts, rubrics). The personal-learning scope does not enforce author/learner separation, but the audit data is captured for when institutional or evaluation scopes need it.
- Enforce `ownership_scope` (`personal` / `institutional`) at the schema level on every `KnowledgeGraph`, `KnowledgeNode`, and `KnowledgeEdge`. Cross-scope references are explicit `GraphReference` links, never edge merges. Personal evidence does not flow into institutional analytics; institutional evidence does not silently appear in personal mastery views. When firm content enters scope, separate deployments are preferred over multi-tenant rows.
- Build the Inspect surface (evidence timeline, current mastery, scheduler decision log, prompt provenance) early enough to debug the engine — Milestone 3 class work, not Milestone 6.
- Ship a backup/export contract in v1 (`lms export --out=jsonl` or equivalent). Personal learning data accumulates value over years; an export path should not be a Phase-4 feature.
- Build small learner, author, LLM-study, graph-design, inspect, and review surfaces early enough to test real workflows.

API style effects:

- REST plus OpenAPI keeps the first API easy to test, document, mock, and expose to agents. It fits resource-heavy backend work such as courses, nodes, attempts, evidence records, reviews, and feedback.
- GraphQL can help later if the frontend needs highly flexible nested graph queries, but it adds resolver, authorization, caching, and observability complexity early.
- Typed RPC can make client/server iteration fast when the whole app is TypeScript-first, but it is less natural if the backend is Python and the app needs stable API contracts for automation, tests, and external integrations.

Workflows review:

- The Workflows repo is Python-first and provides reusable Python CI, autofix, Gate, agent intake, keepalive, verifier, and auto-pilot automation.
- Consumer repos are expected to keep most workflow logic sourced from `stranske/Workflows`; local edits should usually be limited to repo-specific CI wiring, dependency pins, and configuration.
- The consumer template includes LangChain workflow tooling and LLM dependency pins, which aligns with this project's LangChain/LangSmith direction.
- Issues intended for automation should follow the Workflows agent issue format: Why, Scope, Non-Goals, Tasks, Acceptance Criteria, and Implementation Notes.
- Workflows setup implies the repo should be initialized as a GitHub-backed consumer repo before heavy implementation work, with `.github` templates, labels, secrets/environments, Gate, CI, and agent docs installed deliberately.

Suggested day-one data boundaries:

- personal learning data versus institution-owned training data;
- learner performance/evidence records versus content and graph authoring records;
- formative practice data versus summative/current-capability assessment data;
- public/client education analytics versus identifiable learner records;
- LLM traces and prompts versus durable learner evidence;
- restricted strategy/internal content versus public education content;
- accessibility/disability-related signals versus ordinary learner-state data.

Development testing surfaces:

- See [development-testing-surfaces.md](development-testing-surfaces.md) for the working UI/testing outline.

Working Segment 7 decision:

```text
Decision: Use Python, FastAPI, Postgres, REST/OpenAPI, local auth with SSO-ready identity design, and Workflows consumer automation from the beginning.
Context: The first implementation should be local/primitive but should grow toward an institution-ready learning system with LLM support, graph design, current-capability estimates, and testing UI surfaces.
Options considered: Python versus TypeScript; Postgres versus SQLite; REST versus GraphQL versus typed RPC; local auth versus SSO-first; manual repo process versus Workflows automation.
Selected direction: Use Python with FastAPI, SQLAlchemy, Alembic, Pydantic, pytest, Jupyter/pandas for empirical analysis, Postgres first, REST/OpenAPI as the API style, local auth first with SSO-ready modeling, mobile-friendly PWA-ready UI surfaces, a single LLM client wrapper with per-mode model config, day-one LLM cost monitoring with a budget kill-switch, prompt provenance and authoring audit-log fields in the v1 schema, schema-level `ownership_scope` enforcement, an Inspect surface in Milestone 3, a v1 export contract, and Workflows consumer setup after repo initialization. Build a small UI early for testing learner, author, LLM, graph, inspect, and review workflows.
Reasoning: Python aligns with the Workflows consumer system, LangChain/LangSmith integration, backend learning-model work, and testing needs. FastAPI gives REST/OpenAPI contracts naturally. Postgres keeps the data model honest. REST/OpenAPI gives stable contracts and straightforward testing before the UI becomes complex. Workflows should shape issue size, CI, automation, and verification from the start.
Risks: Postgres adds setup weight for local development; REST endpoints may need refinement for graph-heavy UI; Workflows setup adds upfront overhead; auth shortcuts must not block SSO later.
Follow-up questions: What exact local Postgres setup should be used? Which Workflows consumer templates should be copied first? What secrets/environments are available for this repo?
Review date: before Milestone 0 repo setup.
```

Decision output:

- stack decision;
- database decision;
- API style;
- auth assumption;
- first UI surfaces;
- governance minimums.

## Segment 8: Personal-Learning Sustainability And Cadence

Purpose:

- Decide how the system behaves when the project owner uses it irregularly, takes breaks, or runs at low volume.

Questions:

1. What is the realistic daily/weekly attempt volume for the project owner in the first 60 days?
2. What happens to the review queue when the owner is away for a week, two weeks, a month?
3. Should the scheduler ramp up new material aggressively or conservatively during the placeholder-mastery period?
4. How should the system communicate backlog size without producing shame or pressure?
5. At what attempt-volume threshold does empirical mastery-model tuning become viable?

Recommended default:

- Defer the realistic-attempt-volume answer until empirical data exists. The decision becomes load-bearing around Milestone 4-5 (about 30 days of real use); until then, the scheduler runs with conservative defaults (FSRS-4.5 defaults, low new-card introduction rate) so low-volume use does not produce a runaway backlog.
- Implement a pause or vacation mode that freezes review-due times for a declared window. On resume, do not dump the full backlog; introduce overdue items gradually.
- Cap the daily review queue at a configurable maximum (default ~20-30 items). Items beyond the cap defer to the next day. Total backlog is shown as informational, not as obligation.
- Distinguish "not attempted yet," "attempted, due for review," "overdue," and "stale" (very old without attempt). Stale items prompt the learner to re-engage, retire, or adjust the underlying goal — not to plow through.
- Treat backlog-size language as informational and recovery-oriented, not gamified.

Working Segment 8 decision:

```text
Decision: Run the v1 scheduler with conservative defaults during the placeholder-mastery period, defer the cadence-tuning decision until ~30 days of real use, and ship sustainability features (pause mode, daily cap, stale-item handling) before the loop becomes daily-required.
Context: The mastery rule and the scheduler cadence are coupled; tuning either without real attempt data is guessing. Anki and similar systems fail mainly when backlogs become punishing during interruption, not when the algorithm is imperfect.
Options considered: aggressive default ramp; conservative default ramp with explicit later tuning; configurable from day one; no backlog management until needed.
Selected direction: Conservative FSRS-4.5 defaults; pause mode and daily cap shipped in v1; cadence tuning deferred to Milestone 4-5 when real attempt-volume data exists; empirical mastery-model fitting deferred to Milestone 6-7 when ~500-1000 evidence records exist on overlapping nodes.
Reasoning: A scheduler that punishes interruption gets abandoned. A scheduler that ramps slowly is recoverable. The interruption-handling cost is low in v1 and high to retrofit.
Risks: Conservative defaults may feel under-stimulating early. Pause mode can be misused as permanent avoidance. The "stale" category needs a non-shaming UX.
Follow-up questions: What pause durations should be supported? What daily-cap default produces a sustainable load for the project owner? How should the Inspect surface display backlog without anxiety pressure?
Review date: at Milestone 4-5, after 30 days of real use.
```

Decision output:

- placeholder-period scheduler defaults;
- pause/vacation policy;
- daily-cap default;
- stale-item handling;
- cadence-decision review date.

## Segment 9: Privacy And LLM Trace Classification

Purpose:

- Decide how the system retains LLM session data while preserving the project owner's preference for privacy and the system's need for decision-relevant information.

Questions:

1. What traces are decision-relevant (worth retaining as evidence) versus ephemeral (worth expiring quickly)?
2. What PII and personal-reflection patterns should be redacted before traces leave the local system?
3. Which model providers and retention policies satisfy the privacy preference?
4. What user controls should appear in the UI for trace handling?
5. How should institutional/firm content traces differ from personal-learning traces?

Recommended default:

- Every `LLMSession` declares a `trace_class`: `evidence-grade` (assessment-mode attempts, rubric feedback), `formative` (study-coach, practice, exploration), or `ephemeral` (off-topic, chit-chat).
- Retention by class: `evidence-grade` retained as long as the evidence record it supports; `formative` retained for a configurable window (default 60-90 days) to support eval-set construction; `ephemeral` expired in days or not stored verbatim at all.
- **Local-first enforcement order**: classification and PII redaction happen locally in the LLM client wrapper **before** any external trace export. The wrapper holds a redactor that runs on every outbound trace payload; if redaction would strip too much signal, the trace class is demoted to `ephemeral` and the trace is held locally without external export. Classification cannot be a post-hoc cleanup of traces that have already left the local system.
- `ephemeral` traces are never exported verbatim. Only structured outcomes (correctness, confidence, evidence id refs, no transcript text) persist to LangSmith.
- Default model routing: Anthropic API with no training opt-in. LangSmith trace retention configured per class.
- Learner overrides: "keep this trace verbatim" for sessions the learner wants to refer back to; "forget this trace" for sessions the learner wants expunged. The `forget` action triggers (a) local trace deletion, (b) LangSmith deletion via API where supported, (c) preservation of any structured evidence records that survive the verbatim transcript.
- Institutional/firm scope (when it enters) overrides personal defaults with stricter retention, redaction, and access rules.

Working Segment 9 decision:

```text
Decision: Implement trace classification with class-driven retention, default to a privacy-preferring posture, and surface trace handling to the learner.
Context: Personal-learning LLM sessions will carry half-formed thoughts and potentially sensitive professional or personal reflection. Retention should serve evaluation and decision-making, not collection for its own sake. The goal is a healthy preference for preserving privacy while retaining decision-relevant information.
Options considered: no trace retention; retain all traces indefinitely; class-driven retention with learner controls; per-trace consent prompts.
Selected direction: Three trace classes with class-driven retention windows; default Anthropic API with no training opt-in; LangSmith retention configured per class; PII detection on write; learner overrides for keep/forget; institutional override path reserved.
Reasoning: A trace-class enum is cheap to add now and load-bearing later. Defaults should preserve privacy; opt-in keeps verbatim. Class-driven retention scales without per-trace consent UX friction.
Risks: Trace classification mistakes (formative content treated as ephemeral) lose evaluation signal. PII detection has false negatives. Per-trace overrides can confuse the retention model if not audit-logged.
Follow-up questions: What PII detection library or pattern set is good enough for v1? What retention windows should the project owner actually prefer? How should LangSmith retention be configured per trace class?
Review date: before implementing the first LLM study session.
```

Decision output:

- trace-class enum and schema field;
- per-class retention windows;
- default model provider and training-opt-out posture;
- learner override surface;
- institutional override placeholder.

## Segment 10: LLM Cost And Routing

Purpose:

- Decide how the system selects LLM models per task and monitors cost, with the substantive per-mode model choices deferred to empirical data.

Questions:

1. Which LLM modes should default to small/cheap models versus frontier models?
2. What per-mode cost monitoring is needed in v1?
3. What evaluation gold set is needed before substantive model choices can be made empirically?
4. What budget caps or kill-switches should the v1 system enforce?
5. How does cost interact with the trace-class and privacy decisions in Segment 9?

Recommended default:

- Route every LLM call through a single client wrapper. Model selection per mode is configured via env vars or a small config file (`LLM_MODEL_STUDY_COACH`, `LLM_MODEL_PRACTICE`, `LLM_MODEL_TRANSFER`, `LLM_MODEL_AUTHORING_ASSIST`). Switching models is a one-line change.
- Ship cost monitoring in v1 — a daily log line summarizing call count and dollar cost by mode is sufficient. Per-mode visibility is the prerequisite for data-driven model decisions later.
- Build a small LLM evaluation gold set (10-30 hand-curated transcripts with labeled outcomes) before the first `study-coach` flow lands. This is the substrate for replaying prompt/model combinations against expected outcomes in LangSmith.
- Defer substantive per-mode model choices until the gold set and cost data make the comparison meaningful. Sensible starting defaults: small/cheap model for `study-coach` and `practice`; frontier model for `transfer` and `authoring-assist`; revisit after data exists.
- Enforce a daily budget cap with a hard kill-switch in v1, defaulting low. Better to fail-closed early than to discover an unexpected month-end bill.

Working Segment 10 decision:

```text
Decision: Make LLM routing configurable and cost monitoring mandatory from day one; defer substantive per-mode model choices until empirical evaluation data exists.
Context: Per-mode model selection is an empirical question, but the cost of making it empirical-later versus empirical-never depends entirely on whether the routing is configurable. Hardcoding the model in many places turns a future model choice into a refactor.
Options considered: hardcode a single model everywhere; per-mode model selection in code; per-mode model selection in config with cost monitoring and budget caps from v1.
Selected direction: Single LLM client wrapper; per-mode model config; daily cost log line per mode; hard budget kill-switch with low default; LLM evaluation gold set built before first study-coach flow ships; substantive model decisions deferred to data.
Reasoning: The cheapest time to add configurable routing is before the first call site exists. The cheapest time to build the eval gold set is before production traces dominate the dataset. Both decisions are about preserving optionality without front-loading commitment.
Risks: Configurable-but-never-tuned routing decays into "default everywhere." Eval gold set can become stale if the formative-interaction policy changes faster than the set is refreshed. Budget kill-switch may fire during legitimate heavy use.
Follow-up questions: What starting defaults make sense for each LLM mode given current pricing? What daily budget cap matches realistic personal-learning usage? How is the eval gold set versioned alongside the interaction policy?
Review date: after the first study-coach flow has run for a week.
```

Decision output:

- LLM client wrapper interface;
- per-mode model config schema;
- cost log line and budget cap;
- eval gold set construction protocol and storage location;
- model-decision review schedule.

## Suggested Working Order

1. Segment 1: First Product Boundary
2. Segment 2: Learning Model And Mastery
3. Segment 3: LLM Learning Interaction
4. Segment 9: Privacy And LLM Trace Classification
5. Segment 10: LLM Cost And Routing
6. Segment 7: Stack, Governance, And Implementation
7. Segment 4: Knowledge Graphs
8. Segment 8: Personal-Learning Sustainability And Cadence
9. Segment 5: Certification And Current Capability
10. Segment 6: Public Education And Accessibility

This order lets implementation begin after the product boundary, learning model, LLM policy, privacy/cost posture, and stack are clear enough, while preserving the broader design questions for the next pass. Segment 8 lands before Segment 5 because the placeholder-mastery period needs sustainability features before the gap-closing workflow becomes useful.
