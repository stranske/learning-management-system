# Development Testing Surfaces

Status: initial testing UI outline.

This document defines the lightweight interfaces needed during development. These are not polished production screens. They are tools for testing whether the learning engine actually works.

## Testing Goal

The first UI should make the full learning loop observable:

1. select or create a learning goal;
2. inspect content only when useful;
3. attempt an evidence-producing task;
4. receive formative feedback;
5. update current mastery confidence;
6. receive a next action;
7. return later through review or follow-up practice.

Content viewing by itself is not a learning loop. The testing UI should expose where learner action, evidence, feedback, and next-action planning are succeeding or failing.

## Design Defaults

These apply to every surface below.

- Mobile-friendly by default. Use a responsive CSS framework (Tailwind, Pico, or equivalent); avoid desktop-only interactions like hover-to-reveal. A working PWA is on the roadmap; the early surfaces should not foreclose that option.
- Every surface that shows a prompt also shows its `SourceReference` set and provenance (`human` / `llm-assisted` / `llm-generated`, reviewing actor).
- Every surface that shows mastery shows the evidence supporting it and the model attribution (FSRS-4.5 placeholder vs. learned model, when applicable).
- Surfaces handle empty states gracefully — the early system will have very few prompts, attempts, and nodes.
- The Inspect surface lands in Milestone 3, not at the end, so the engine is debuggable from the moment it runs.

## Surface 1: Learner Loop

Purpose:

- Test the core learner experience from goal to next action.

Needed early:

- current goal or course path;
- assigned next task;
- prompt or activity view;
- learner response input;
- confidence rating;
- optional reference access with tracking;
- formative feedback display;
- next action;
- current mastery status language;
- review queue preview;
- source citation panel shown after the attempt (linked `SourceReference` set);
- prompt provenance indicator (human-authored, LLM-assisted, LLM-generated).

Questions this surface should answer:

- Does the learner understand what to do next?
- Does the system produce evidence from the activity?
- Does feedback lead to a concrete next action?
- Does the mastery language feel useful without overstating certainty?

## Surface 2: LLM Study Session

Purpose:

- Test whether the LLM interaction follows learning principles.

Needed early:

- session mode selector: `study-coach`, `practice`, later `transfer`;
- coaching intensity control: full coaching, light nudges, quiet mode;
- reminder shown when a learner disables preferred formative guidance;
- prompt/response transcript;
- visible nudges when learner behavior creates learning risk;
- source/context panel for approved content;
- trace/session identifier for LangSmith review;
- mode flag for formative versus assessment-restricted sessions;
- trace-class indicator (`evidence-grade` / `formative` / `ephemeral`);
- per-session cost indicator;
- learner keep/forget controls for trace retention;
- model identity for the session (which model handled the call);
- visual flag on uncited LLM claims (`unverified`).

Questions this surface should answer:

- Does the LLM ask for retrieval or application when the session calls for it?
- Does it answer directly when direct explanation is instructionally appropriate?
- Do nudges feel useful rather than obstructive?
- Can the system distinguish formative interaction from assessment conditions?

## Surface 3: Authoring And Content Setup

Purpose:

- Test whether a learning object can be authored with enough structure to drive evidence, feedback, review, and graph relationships.

Needed in v1 / Phase 1 (Milestone 2-3):

- learning goal editor (knowledge-type-tagged);
- knowledge node editor (with `ownership_scope`);
- prerequisite-edge picker;
- prompt editor (with `SourceReference` selector, demand level, intended cognitive action, expected answer form);
- `SourceReference` editor showing `drift_status` and a re-confirm action when source content has changed;
- prompt provenance display (`authoring_method`, `authoring_actor`, `reviewing_actor`, `approval_timestamp`, `llm_model` if applicable);
- draft / published status with a publication gate (prompts can only be authored against published nodes; LLM-proposed nodes/edges require human approval).

Deferred to Phase 2+ (Milestone 5+, when institutional curriculum authoring lands):

- course / module / lesson editor;
- separate `LearningObjective` editor (folded into `LearningGoal` for v1);
- feedback template editor (v1 feedback is a structured field on `Attempt`);
- review policy selector (v1 uses scheduler defaults per knowledge type);
- principle-link picker as a UI affordance (v1 references YAML principle IDs by hand; validator runs at build time).

Questions this surface should answer:

- Can an author create a lesson that is more than content storage?
- Are objectives, prompts, feedback, and review rules connected?
- Does the authoring flow force enough learning-design clarity without becoming unusable?

## Surface 4: Knowledge Graph Studio

Purpose:

- Test graph design for both institution-authored and learner-authored goals.

Needed early:

- node list;
- node detail;
- edge editor;
- graph visualization or adjacency view;
- edge type selector;
- edge confidence;
- graph version;
- learner goal graph editor;
- graph-performance signal list.

Questions this surface should answer:

- Can a user create a practical graph without over-modeling?
- Are prerequisite and competency relationships visible enough to debug?
- Can learner performance reveal missing prerequisites, weak edges, or confusing contrasts?

## Surface 5: Evidence And Mastery Inspector

Purpose:

- Test whether the system's current-capability estimates are explainable.
- Make the engine debuggable from Milestone 3, not at the end. This surface is load-bearing for diagnosing the scheduler and the placeholder mastery rule before more features land on top of them.

Needed early:

- learner evidence timeline;
- mastery estimate by node/objective;
- historical demonstrations;
- current confidence;
- recency and decay indicators;
- support level and reference-use markers;
- confidence-versus-performance comparison;
- next evidence needed;
- model attribution per estimate (FSRS-4.5 placeholder vs. learned model, when applicable);
- scheduler decision log entries that touched the node;
- prompt-provenance and source-drift status for prompts that contributed evidence.

Questions this surface should answer:

- Can a human understand why the system estimates current mastery the way it does?
- Is the estimate too confident, too vague, or too hard to interpret?
- Does the system know what evidence would improve confidence?

## Surface 6: Review Queue And Scheduler Debugger

Purpose:

- Test review assignment and next-action logic.

Needed early:

- due review list;
- scheduler reason codes;
- task type: new learning, review, remediation, transfer, assessment;
- review interval;
- priority;
- blocked/available status;
- manual override for testing;
- scheduler decision log;
- pause/vacation mode toggle and status;
- daily cap configuration and current backlog total (informational, not gamified);
- stale-item flag and re-engagement / retire / adjust-goal options.

Questions this surface should answer:

- Does the next task make sense?
- Can the system explain why a review or remediation task appeared?
- Are scheduler decisions using evidence rather than content order alone?

## Surface 7: Current Capability And Gap Analysis

Purpose:

- Test the nonpunitive certification/current-capability model.

Needed early:

- capability target definition;
- target objectives/nodes;
- current estimate;
- confidence level;
- evidence gaps;
- required evidence;
- gap-closing plan;
- maintenance/review plan.

Questions this surface should answer:

- Can the system describe what a learner appears able to do now?
- Can it compare current evidence with a target without treating certification as permanent?
- Does the gap plan produce useful next work?

## Surface 8: Coach Or Manager Testing Dashboard

Purpose:

- Test support signals without building premature surveillance.

Needed early:

- local/testing-only learner list;
- learners needing support;
- reason for support signal;
- evidence summary;
- recommended intervention;
- privacy/sensitivity marker;
- intervention log.

Questions this surface should answer:

- Are support signals actionable?
- Do they avoid raw activity surveillance?
- Does the dashboard preserve uncertainty and sensitivity?

## Surface 9: Public Education Prototype

Purpose:

- Test low-stakes public/client education without over-prioritizing it.

Needed early:

- public learning path view;
- plain-language content;
- low-stakes understanding checks;
- misconception feedback;
- aggregate understanding report;
- explanation variant comparison.

Questions this surface should answer:

- Can public learners check understanding without feeling graded?
- Can the institution identify common misconceptions?
- Which explanations appear to improve understanding?

## Surface 10: Developer/Research Review Console

Purpose:

- Test research provenance, claim status, and LLM quality review.

Needed early:

- learning principle list;
- claim status;
- source links;
- intervention mapping;
- LangSmith trace links;
- LLM-session quality review rubric;
- research scan queue;
- evidence-review notes.

Questions this surface should answer:

- Can product behavior be traced back to research claims?
- Are LLM sessions staying aligned with the formative-learning policy?
- Which claims or prompts need review before implementation continues?

## Surface 11: Accessibility And Reading Stress Test

Purpose:

- Test whether the architecture can support dyslexic reading-learning needs without overgeneralizing from adult professional training.

Needed before implementation:

- fine-grained reading-skill graph sketch;
- phonological-awareness node examples;
- decoding-fluency evidence examples;
- reading-comprehension assessment examples;
- working-memory and cognitive-load annotations;
- motivation and reward pattern inventory;
- frustration-sensitive feedback examples;
- accessibility-support checklist;
- domain-specific research review status.

Questions this surface should answer:

- Does the graph model support much finer-grained prerequisite structure?
- Can the evidence model represent decoding fluency and reading comprehension separately?
- Do motivation and reward features reinforce productive practice rather than shallow completion?
- Are working-memory and cognitive-load constraints visible in task design?
- What reading-specific claims require research review before product use?

## Early UI Recommendation

Build the first UI as a small internal web app with five tabs:

1. Learn
2. LLM Study
3. Author
4. Graph
5. Inspect

The later tabs can expand into Review Queue, Capability, Coach, Public Education, Accessibility/Reading, and Research Review once the backend supports those records.
