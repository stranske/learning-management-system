# Capability Preview Surface Decision

Status: accepted

## Context

The Phase 1 Minimum Demo remains the Milestones 0-4 thesis-validation gate:
source-backed note import, prompt authoring, learner attempts, verbose evidence,
Inspect mastery, review queue reasons, formative study-coach sessions, and the
pre-registered day-30 retention protocol.

The repo now also contains mounted personal capability and gap-analysis routes:

- `/capability/*`
- `/app/learner/capability`

Those routes are real authenticated product work, but they implement a later
personal gap-closing surface. Removing or hiding them would discard completed
M5/M6 implementation, while treating them as Minimum Demo evidence would blur
the Phase 1 acceptance contract.

## Decision

Keep the capability API and learner UI mounted as authenticated preview and
post-demo surfaces. They may support exploratory review, later milestone work,
and personal gap-closing flows, but they do not satisfy the Minimum Demo.

Minimum Demo readiness must be judged only by the Milestones 0-4 core learner
loop and retention protocol. Capability targets, estimates, gap analyses, and
maintenance plans remain outside that readiness claim until the core learner
loop gate has passed.

## Consequences

- Do not remove `capability_router` or `capability_ui_router` from the app.
- Do not delete capability API, UI, model, migration, or test coverage.
- Demo and handoff docs should describe `/capability/*` as preview/post-demo
  functionality when they mention it.
- Minimum Demo docs must not list capability routes or capability entities as
  required demo steps.
