# Architecture

This directory is the navigation index for architecture-relevant content. Substantive design lives in `docs/product/` and `docs/product/early-design-decisions.md`; these docs link to those sources rather than duplicating them.

## Decision Records

Architecture decisions are recorded under `decision-records/` using the structured shape from `docs/product/early-design-decisions.md` (Context / Options considered / Selected direction / Reasoning / Risks / Follow-up questions / Review date).

- [0001 — Backend stack and product boundary](decision-records/0001-backend-stack-and-boundary.md)
- [Security assumptions](security-assumptions.md)

## Where the Authoritative Design Content Lives

These are the canonical sections; this index links to them so future architecture work doesn't drift from the source-of-truth design corpus.

| Topic | Canonical location |
| --- | --- |
| Project thesis and Phase 1 / Milestones 0-4 boundary | [Initial Product Boundary](../product/project-plan.md#initial-product-boundary) and [Phase 1 Minimum Core](../product/project-plan.md#phase-1-minimum-core) |
| API surface (v1 vs Phase 2+) | [API Surface Sketch](../product/project-plan.md#api-surface-sketch) |
| Mastery model (FSRS-4.5 placeholder, computed view, EvidenceRecord schema) | [Mastery Is An Evidence-Backed Estimate](../product/project-plan.md#4-mastery-is-an-evidence-backed-estimate) |
| Source citation + content-hash drift detection | [Retrieval And Assessment Engine](../product/project-plan.md#retrieval-and-assessment-engine) |
| Prompt provenance + authoring audit log | [Retrieval And Assessment Engine](../product/project-plan.md#retrieval-and-assessment-engine) |
| SchedulerEvidenceAdapter (EvidenceRecord -> FSRS rating) | [Review Scheduler](../product/project-plan.md#review-scheduler) |
| Ownership-boundary enforcement (repository pattern + DB CHECK + tests + future RLS) | [Knowledge Graph](../product/project-plan.md#knowledge-graph) |
| Security assumptions (secrets, local-only sources, trace handling, SSO readiness) | [docs/architecture/security-assumptions.md](security-assumptions.md) |
| Knowledge Graph Bootstrap (v1 importers + LLM proposals + publication gate) | [Knowledge Graph](../product/project-plan.md#knowledge-graph) |
| Export / import contract (`lms export`, `lms import --dry-run`, `lms import --apply`) | [Milestone 3: Knowledge Graph, Evidence, And Inspect](../product/project-plan.md#milestone-3-knowledge-graph-evidence-and-inspect) |
| LLM client wrapper interface (budget preflight + trace classification + redaction + replay) | [LLM Learning Interaction Layer](../product/project-plan.md#llm-learning-interaction-layer) |
| Personal-learning sustainability (pause mode, daily cap, stale items) | [Segment 8: Personal-Learning Sustainability And Cadence](../product/early-design-decisions.md#segment-8-personal-learning-sustainability-and-cadence) |
| Privacy + LLM trace classification (local-first redaction) | [Segment 9: Privacy And LLM Trace Classification](../product/early-design-decisions.md#segment-9-privacy-and-llm-trace-classification) |
| LLM cost + routing | [Segment 10: LLM Cost And Routing](../product/early-design-decisions.md#segment-10-llm-cost-and-routing) |
| Minimum Demo Criterion (8-item pre-registered day-30 retention) | [Minimum Demo Criterion](../product/project-plan.md#minimum-demo-criterion) |

## How to Add a Decision Record

1. Number it sequentially after the latest record in `decision-records/`.
2. Use the structured shape: Decision, Context, Options considered, Selected direction, Reasoning, Risks, Follow-up questions, Review date.
3. Link from this index under "Decision Records."
4. If the decision modifies content in `docs/product/`, update the canonical doc as part of the same PR.
