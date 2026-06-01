"""LMS app behavior baseline kit.

Built on the shared ``baseline_kit`` package -- this directory contains only the
app-specific pieces (adapter, catalog, invariant bounds). The generic harness
(directional engine, invariant assertion, golden glue, coverage manifest) is
imported from ``baseline_kit``, the same core the TMP / PAEM / trip-planner /
Counter_Risk kits use.

Target surface: ``lms.scheduling.service.schedule_from_attempt`` -- the v1
spaced-repetition review scheduler. Given a learner *attempt* and its scored
*evidence record*, it classifies a retrieval signal (fail / low-confidence
success / success), consults the deterministic FSRS rating adapter, and emits a
single ``ReviewQueueItem`` with a due date, a reason code, and a priority.

Unlike the Counter_Risk concentration surface (a pure compute), this surface is
DB-backed: it queries prior completed reviews to step a success interval ramp
and writes durable schedule / decision rows. The adapter therefore stands up an
in-memory SQLite session per scenario, seeds the requested number of prior
completed reviews, runs the scheduler at a FIXED ``now``, and reduces the
resulting queue item + decision log to a flat ``dict[str, float | int]`` -- the
contract ``baseline_kit`` consumes.
"""
