# Architecture

This directory is the navigation index for architecture-relevant content. Substantive design lives in `docs/product/` and `docs/product/early-design-decisions.md`; these docs link to those sources rather than duplicating them.

## Decision Records

Architecture decisions are recorded under `decision-records/` using the structured shape from `docs/product/early-design-decisions.md` (Context / Options considered / Selected direction / Reasoning / Risks / Follow-up questions / Review date).

- [0001 — Backend stack and product boundary](decision-records/0001-backend-stack-and-boundary.md)

## Where the Authoritative Design Content Lives

These are the canonical sections; this index links to them so future architecture work doesn't drift from the source-of-truth design corpus.

| Topic | Canonical location |
| --- | --- |
| Project thesis and Phase 1 / Milestones 0-4 boundary | [docs/product/project-plan.md](../product/project-plan.md) "Initial Product Boundary," "Phase 1 Minimum Core" |
| API surface (v1 vs Phase 2+) | [docs/product/project-plan.md](../product/project-plan.md) "API Surface Sketch" |
| Mastery model (FSRS-4.5 placeholder, computed view, EvidenceRecord schema) | [docs/product/project-plan.md](../product/project-plan.md) "Mastery Is An Evidence-Backed Estimate" |
| Source citation + content-hash drift detection | [docs/product/project-plan.md](../product/project-plan.md) Retrieval And Assessment Engine "Source citation policy" |
| Prompt provenance + authoring audit log | [docs/product/project-plan.md](../product/project-plan.md) "Prompt provenance" |
| SchedulerEvidenceAdapter (EvidenceRecord → FSRS rating) | [docs/product/project-plan.md](../product/project-plan.md) Review Scheduler "SchedulerEvidenceAdapter" subsection |
| Ownership-boundary enforcement (repository pattern + DB CHECK + tests + future RLS) | [docs/product/project-plan.md](../product/project-plan.md) Knowledge Graph "Ownership-boundary enforcement" |
| Knowledge Graph Bootstrap (v1 importers + LLM proposals + publication gate) | [docs/product/project-plan.md](../product/project-plan.md) "Knowledge Graph Bootstrap (v1)" |
| Export / import contract (`lms export`, `lms import --dry-run`, `lms import --apply`) | [docs/product/project-plan.md](../product/project-plan.md) Milestone 3 "Export and import contract (v1)" |
| LLM client wrapper interface (budget preflight + trace classification + redaction + replay) | [docs/product/project-plan.md](../product/project-plan.md) LLM Layer "Operational requirements" + "LLM client wrapper interface (v1)" |
| Personal-learning sustainability (pause mode, daily cap, stale items) | [docs/product/early-design-decisions.md](../product/early-design-decisions.md) Segment 8 |
| Privacy + LLM trace classification (local-first redaction) | [docs/product/early-design-decisions.md](../product/early-design-decisions.md) Segment 9 |
| LLM cost + routing | [docs/product/early-design-decisions.md](../product/early-design-decisions.md) Segment 10 |
| Minimum Demo Criterion (8-item pre-registered day-30 retention) | [docs/product/project-plan.md](../product/project-plan.md) "Minimum Demo Criterion" |

## How to Add a Decision Record

1. Number it sequentially after the latest record in `decision-records/`.
2. Use the structured shape: Decision, Context, Options considered, Selected direction, Reasoning, Risks, Follow-up questions, Review date.
3. Link from this index under "Decision Records."
4. If the decision modifies content in `docs/product/`, update the canonical doc as part of the same PR.
