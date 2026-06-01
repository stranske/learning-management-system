# LMS app behavior baseline kit

Scenario-driven wiring / sensibility / regression tests for the spaced-repetition
review scheduler, built on the shared **`baseline_kit`** package. Only the
app-specific pieces live here.

## Requires

`baseline_kit` (the shared core) must be importable. It lives in
`stranske/Workflows` under `packages/app-baseline-kit`:

```bash
pip install "app-baseline-kit @ git+https://github.com/stranske/Workflows.git#subdirectory=packages/app-baseline-kit"
```

It is declared in this repo's `pyproject.toml` `[project.optional-dependencies]
dev`, so `pip install -e ".[dev]"` pulls it (plus `pytest-regressions`, which
uses the `num_regression` fixture backed by `numpy` + `pandas` — both already
core LMS dependencies).

## Target surface

`lms.scheduling.service.schedule_from_attempt` — the **v1 review scheduler**.
Given a learner *attempt* and its scored *evidence record*, it:

1. counts prior completed reviews for that learner + knowledge node,
2. classifies a retrieval signal (`fail` / `low-confidence-success` /
   `success`), blending the internal classifier with the deterministic FSRS
   rating adapter (`lms.scheduling.fsrs_adapter`) conservatively,
3. emits one `ReviewQueueItem` with a `due_at`, a `reason_code`
   (`remediation` / `due-review`), and a `priority`, plus durable
   schedule/decision rows.

The policy is a fixed interval ramp `1 → 3 → 7 → 14 → 28` days
(`SUCCESS_INTERVALS_DAYS`), **not** classic SM-2 — there is no per-item
`ease_factor` or mutable `repetition_count`. See "Metrics" below for the
faithful scalar analogues.

This surface is **DB-backed**, so the adapter stands up an in-memory SQLite
session per scenario (mirroring `tests/conftest.py::db_session`), seeds the
requested prior history, runs the scheduler at a fixed `now`, then reduces the
queue item to scalars.

## Layout

```
adapter.py                # evidence signal + prior history -> flat scalar dict (the only app glue)
catalog.yaml              # base scenario + signal variants + directional checks
invariants.py             # policy bounds -> baseline_kit.InvariantResult
test_golden.py            # golden master of each scenario's flattened decision
test_directional.py       # metamorphic checks (fail -> shorter+reset; repeat success -> longer ...)
test_invariants.py        # invariants on base + every scenario
test_coverage_manifest.py # metric-key coverage -> docs/reports/baseline-coverage.md
```

## Scenario model

A *scenario* is a flat bundle of the evidence signal fields the scheduler keys
on (`correctness`, `normalized_score`, `confidence_rating`, `support_level`,
`response_time_seconds`, `transfer_distance`) plus an optional `prior_successes`
count of completed prior reviews to seed first (each one steps the success
ramp). Variants perturb one dimension so the directional movement is
predictable (fail → reset; low confidence / support / partial score →
shortened + lower FSRS rating; repeated success → longer interval).

## Metrics (the flat scalar dict)

| key | meaning |
|-----|---------|
| `next_interval_days` | days from `now` to emitted `due_at` (0 = immediate remediation) |
| `repetition_count` | prior completed reviews the scheduler read (advances the ramp) |
| `fsrs_rating_value` | FSRS rating `1=again .. 4=easy`; `0` when excluded/None |
| `signal_severity` | blended signal ordinal `0=fail, 1=low-confidence, 2=success` |
| `priority` | queue priority (`0.9` remediation, `0.7` low-confidence, `0.4` success) |
| `is_reset` | `1` when the decision resets to an immediate remediation item |
| `is_remediation` / `is_due_review` | one-hot reason-code flags |
| `fsrs_scheduling_included` | `1` when the FSRS rating feeds the interval calc |

There is deliberately **no invented `ease_factor`**: the surface does not store
one. `fsrs_rating_value` is the closest real "grade/ease" severity signal it
produces.

## Running

```bash
PYTHONHASHSEED=0 pytest tests/baseline/                       # full suite
pytest tests/baseline/test_golden.py --force-regen            # re-bless after an intended change
BASELINE_REFRESH_REPORT=1 pytest tests/baseline/test_coverage_manifest.py  # refresh report
```

## Invariants enforced

Grounded in `lms.scheduling.service` (`SUCCESS_INTERVALS_DAYS`,
`LOW_CONFIDENCE_INTERVAL_DAYS`, the `_decide` branches, the
`ReviewQueueItem.priority` CHECK constraint):

- `0 <= priority <= 1`
- `next_interval_days >= 0` and `<= max(SUCCESS_INTERVALS_DAYS)` (= 28)
- `repetition_count >= 0`
- `0 <= fsrs_rating_value <= 4`; `0 <= signal_severity <= 2`
- reason flags are one-hot (`is_remediation + is_due_review == 1`)
- `is_reset == is_remediation`
- a `fail` signal ⇒ reset, interval 0, priority 0.9
- a non-fail signal ⇒ never resets, is a due-review
- a low-confidence success ⇒ due within `LOW_CONFIDENCE_INTERVAL_DAYS` (1 day)
- a clean success ⇒ priority 0.4 (lowest band) and a due-review
