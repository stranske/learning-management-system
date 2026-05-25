# Project Review Brief For Local Agent

Status: handoff brief for second review.

This brief is intended for a local agent reviewing the project without access to the conversation history.

## Local Context

- Project folder: `/Users/teacher/Library/CloudStorage/Dropbox/Learning/Code/Learning-Management-System`
- Current state: documentation and design only; no application code yet.
- Git state: this folder is not currently an initialized Git repository.
- Related local process repo: `/Users/teacher/Library/CloudStorage/Dropbox/Learning/Code/Workflows`
- Source research includes local notes on *How Do We Learn?* and a local PDF outline of *The Math Academy Way*.

## Project Summary

The project is an API-first learning management system intended to be a learning engine rather than a content warehouse. Its core responsibility is to help learners build durable, usable knowledge through learner action, retrieval, feedback, spacing, transfer, graph-structured knowledge, current-capability estimates, and formative LLM interaction.

The system should support multiple audience families:

- personal learning from reading, notes, and projects;
- new analyst training for investment philosophy, workflows, judgment, and firm practices;
- company-wide onboarding and continuing education;
- public-facing education, especially later public pension client education;
- accessibility-sensitive learning use cases, with dyslexic reading used as a design stress test.

The current design is intentionally broad but implementation should begin locally and concretely with the project owner as first user and personal learning from the collected research notes as the first content path.

## Research Foundation

The design is grounded primarily in:

- Hector Ruiz Martin, *How Do We Learn?*, summarized in [research/learning-principles.md](research/learning-principles.md) and section files under [research/](research/).
- Justin Skycak, advised by Jason Roberts, *The Math Academy Way*, summarized in [research/math-academy-way/](research/math-academy-way/).
- Comparative synthesis in [research/math-academy-way/synthesis-with-how-do-we-learn.md](research/math-academy-way/synthesis-with-how-do-we-learn.md).

The research synthesis says:

- use Ruiz Martin for evidence hygiene, learning mechanisms, feedback, assessment, motivation, emotion, transfer, and caution against overclaiming;
- use Math Academy as an implementation pattern library for adaptive learning infrastructure, especially knowledge graphs, diagnostics, scheduling, review, remediation, and learner accountability;
- preserve Math Academy-specific product claims as reviewable claims, not adopted assumptions.

## Current Design Direction

Primary design thesis:

- The LMS should not merely host content. It should assign meaningful learner actions, gather evidence, update current capability estimates, provide feedback, schedule review, and recommend next actions.

Core commitments:

- completion is not learning evidence;
- learner action must be observable;
- knowledge should be graph-structured where the domain supports it;
- mastery is a changing current-capability estimate, not a final boolean;
- retrieval, spacing, interleaving, and remediation should drive scheduling;
- feedback should create a next action;
- transfer must be designed and measured;
- accountability can include standards and pressure but must avoid shame and shallow compliance;
- research claims must remain reviewable and periodically refreshed.

## Decisions Already Made

See [product/early-design-decisions.md](product/early-design-decisions.md) for the durable decision record. Current working decisions:

1. First prototype: local/primitive; project owner is first real user; personal/research-note learning is first content path, without narrowing the architecture to only that use case.
2. Mastery: represent as multidimensional current-capability estimate using evidence type, recency, support level, reference use, confidence, correctness, transfer, and human review.
3. LLM: LangChain/LangGraph and LangSmith are core. Start with `study-coach` and `practice` modes. Use a research-derived formative interaction policy with learner controls and assessment overrides.
4. Graphs: support personal and institutional graphs; implement personal/research-note graph first. Version-one edge types are prerequisite, supports-objective, supports-competency, related, contrast, transfer-context, and interference-risk.
5. Certification: use time-bounded `CertificationSnapshot` and current-capability estimates. Pair gaps with a learning path. Avoid permanent certification language.
6. Public/accessibility: public pension education is a later pilot; dyslexic reading is a design stress test. Motivation/reward, phonological awareness, decoding fluency, reading-comprehension assessment, and working-memory/cognitive-load design are especially important.
7. Stack: Python, FastAPI, SQLAlchemy, Alembic, Pydantic, pytest, Postgres, REST/OpenAPI, local auth with SSO-ready identity, and Workflows consumer automation.

## Key Product Docs

- [docs/README.md](README.md): documentation map and review notes.
- [product/project-plan.md](product/project-plan.md): main design plan and architecture.
- [product/early-design-decisions.md](product/early-design-decisions.md): working decision record.
- [product/development-testing-surfaces.md](product/development-testing-surfaces.md): UI/testing surfaces for development.
- [product/research-domain-model.md](product/research-domain-model.md): research-to-product conceptual data model.

## Key Research Docs

- [research/learning-principles.md](research/learning-principles.md): main learning principles register.
- [research/references.md](research/references.md): reusable citations.
- [research/math-academy-way/synthesis-with-how-do-we-learn.md](research/math-academy-way/synthesis-with-how-do-we-learn.md): synthesis of the two major resources.
- [research/math-academy-way/part-01-preliminaries.md](research/math-academy-way/part-01-preliminaries.md) through [research/math-academy-way/part-06-faq-backmatter.md](research/math-academy-way/part-06-faq-backmatter.md): detailed second-pass Math Academy outline.
- [research/section-05-03-assessment-summary.md](research/section-05-03-assessment-summary.md), [research/section-05-02-feedback-summary.md](research/section-05-02-feedback-summary.md), [research/section-02-03-memory-processes-summary.md](research/section-02-03-memory-processes-summary.md), [research/section-02-05-transfer-of-learning-summary.md](research/section-02-05-transfer-of-learning-summary.md), and [research/section-04-01-metacognition-summary.md](research/section-04-01-metacognition-summary.md) are especially relevant to early implementation.

## Workflows Process Context

The project is expected to use the local Workflows process once initialized as a GitHub repo. Important local references:

- `/Users/teacher/Library/CloudStorage/Dropbox/Learning/Code/Workflows/templates/consumer-repo/README.md`
- `/Users/teacher/Library/CloudStorage/Dropbox/Learning/Code/Workflows/templates/consumer-repo/AGENTS.md`
- `/Users/teacher/Library/CloudStorage/Dropbox/Learning/Code/Workflows/templates/consumer-repo/docs/AGENT_ISSUE_FORMAT.md`
- `/Users/teacher/Library/CloudStorage/Dropbox/Learning/Code/Workflows/templates/consumer-repo/docs/CI_SYSTEM_GUIDE.md`

Implications:

- local workflow files should mostly come from the Workflows consumer template;
- issues should use Why, Scope, Non-Goals, Tasks, Acceptance Criteria, and Implementation Notes;
- most workflow behavior belongs in Workflows rather than local edits;
- repo setup should account for Gate, CI, labels, secrets/environments, agent intake, verifier, and keepalive.

## Review Requests

Please review:

- whether the architecture is coherent and implementable;
- whether the first implementation slice is still too broad;
- whether the data model implied by the design is internally consistent;
- whether the LLM learning interaction policy is specific enough to build and evaluate;
- whether the knowledge graph design balances usefulness and humility;
- whether certification/current capability is modeled clearly enough;
- whether public education and dyslexic reading are properly represented as later pilot/stress-test constraints;
- whether the Workflows process creates additional setup requirements before implementation.

## Likely Next Step After Review

After the second review, convert Milestone 0 and the first backend slice into Workflows-ready issues:

1. initialize Git/GitHub repo and Workflows consumer setup;
2. scaffold FastAPI/Postgres project;
3. implement initial models for users, learners, objectives, knowledge nodes/edges, prompts, attempts, evidence records, mastery estimates, and feedback;
4. add minimal UI surfaces for Learn, LLM Study, Author, Graph, and Inspect.
