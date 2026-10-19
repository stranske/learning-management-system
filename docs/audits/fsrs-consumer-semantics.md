# Evidence-to-FSRS consumer audit — issue #762

Audited 2026-10-19 at `f96d3848fe3565a90fb2772c701d72861d71c948`.
This delivery adds offline prevention checks and an inventory; production
scheduling code, policy, FSRS parameters and interval algorithms are unchanged.

## Boundary inventory

The finite seam is `FSRS_RULES` / `evidence_to_fsrs_rating`, timing-population
selection, rating/signal conversion and their direct scheduling/state consumers.
The machine-checkable source of truth is `FSRS_SEAM_INVENTORY` in
`src/lms/scheduling/fsrs_adapter.py` (kinds: rating-adapter, rating-rule,
signal-adapter, consumer), asserted complete against `FSRS_RULES` by
`test_seam_inventory_covers_every_rating_rule` and
`test_seam_inventory_records_adapters_consumers_and_dispositions`.
Call-site search: `rg -n 'evidence_to_fsrs_rating|_fsrs_to_signal|_signal_to_rating_value|schedule_for_evidence|schedule_from_attempt' src/lms`.

| Producer → consumer | Contract / observed state | Evidence / disposition |
|---|---|---|
| `evidence.repository.create_attempt` → `evidence.service.record_attempt` → `schedule_for_evidence` | Scored evidence enters scheduling in the same HTTP transaction; unscored evidence waits for grading | Existing attempt-loop tests and new 12-case HTTP matrix; confirmed |
| `ui.attempts.self_grade_attempt_route` → `schedule_for_evidence` | Preserve binary versus partial-credit scoring method, confidence and support flags | Existing UI self-grade / binary adapter and HTTP tests; confirmed |
| `feedback.scoring.score_attempt_against_rubric` → `schedule_for_evidence` | Normalize the current rubric score and schedule its evidence; no new rating policy | Existing rubric-scoring tests; confirmed within tested cases |
| `feedback.repository._ensure_revision_scheduling` → `schedule_for_evidence` | Schedule revision evidence when no queue item exists | Existing revision request tests; confirmed within tested cases. This caller selects the first evidence by ID; behavior for multiple later grades is static-only / unknown here |
| `service._prompt_class_timing_context` → `evidence_to_fsrs_rating(sample)` | Filter prior same-learner, ownership-scoped prompt-class evidence, latest grade before eligibility, one timing sample per attempt | Existing HTTP/timing suite; new cases establish a real three-sample timing population; confirmed |
| `service.schedule_from_attempt` → `evidence_to_fsrs_rating` → exclusion gate | `scheduling_included=false` returns a receipt before any card/queue/schedule/decision mutation | Existing cold/existing-card transfer controls and new persisted near/far/novel cases; confirmed |
| `service._fsrs_to_signal` / `_classify_signal` / `_conservative_signal` → `_signal_to_rating_value` | Conservative signal blending retains Easy=4 on success, caps supported/low confidence, and intentionally permits fallback for insufficient signal | Existing boundaries and new real-engine rating capture; confirmed for ordinary tested inputs; non-finite exception below |
| `card_state.advance_card_state` → `fsrs_engine.review` → `ReviewCardState` | Real FSRS executes, then serialized state, review count and due date persist | New recording spy calls the actual engine and a fresh session checks the committed card; confirmed |
| queue creation → `_record_schedule_and_decision` → `ReviewSchedule` / `SchedulerDecision` | Queue evidence/attempt identity, due date and linked durable decision agree | New matrix joins schedules and decisions to the exact attempt's queue item; confirmed |
| excluded result → evidence service / revision handling | Excluded receipt becomes `review_queue_item=None`, not a fabricated dated queue | Existing transfer tests, new committed exclusion/card freeze checks; confirmed |

## Complete rule inventory

The order in `FSRS_RULES` is policy-significant. These rows enumerate all nine
rules and the final fallback, rather than treating every score as binary.

| Rule | Adapter rating / inclusion | Consumer evidence and disposition |
|---|---|---|
| transfer-excluded | excluded / None / false | Near, far, novel keep every existing card column and create no queue/schedule/decision; confirmed |
| incorrect | Again / 1 / true | Explicit incorrect precedes numeric score; actual engine 1 and persisted effects; confirmed |
| insufficient-signal (non-finite guard) | Again / 1 / true | Adapter non-finite tests pass; scheduler fallback can lose this verdict: confirmed additional finding below |
| supported-or-low-confidence-correct | Hard / 2 / true | Actual hint/reference API fields reach engine 2; existing low-confidence controls cover nullable-confidence boundary; confirmed |
| partial-under-half | Again / 1 / true | 0.49 reaches engine 1; confirmed |
| partial-under-mastery | Hard / 2 / true | 0.50 and 0.84 reach engine 2; confirmed |
| partial-at-mastery | Good / 3 / true | Explicit partial-credit 0.85 reaches engine 3; confirmed |
| fast-first-attempt | Easy / 4 / true | Binary correct, confidence 5, elapsed 1 with three real eligible 40-second prior samples reaches engine 4; confirmed |
| unsupported-correct | Good / 3 / true | Binary correct, confidence 4 reaches engine 3 even with eligible timing history; confirmed |
| final insufficient-signal fallback | Again / 1 / true | Adapter defaults conservatively; service explicitly returns to the internal classifier for this rule. Do not infer raw adapter value equals final engine value; intentional fallback mechanism, limited evidence on all input combinations |

## Known owners and additional finding

Known transfer loss is owned by [source #760](https://github.com/stranske/learning-management-system/issues/760), delivered in [PR #779](https://github.com/stranske/learning-management-system/pull/779).
Known Easy/Good and upstream score-selection work is owned by
[source #761](https://github.com/stranske/learning-management-system/issues/761),
delivered in [PR #781](https://github.com/stranske/learning-management-system/pull/781).
Those merges are implementation evidence; this audit does not claim their
independent source acceptance or verifier completion.

**Additional confirmed internal-path loss, returned for scope review:** with
`correctness=True`, confidence 5, no normalized score, raw score infinity and
max score 1, the pure adapter returns Again=1 / insufficient-signal. The real
scheduler's `_fsrs_to_signal` drops this explicit result because of its rule ID;
the internal classifier returns success, and the card advances with a future
due date while the decision still logs the adapter's Again=1.
The [reproducer](evidence/fsrs-consumer-762/lms762-nonfinite-probe.py) uses the
real repository, scheduler and database, commits and rereads state; its
[observed output](evidence/fsrs-consumer-762/lms762-nonfinite.txt) is retained.
Run from the repository root: `PYTHONPATH=src:. python docs/audits/evidence/fsrs-consumer-762/lms762-nonfinite-probe.py`.
This proves the direct/internal evidence path only. Public API reachability of
such a value is unknown; no live request, production fix, new rating policy or
automatic follow-up issue is included. The existing audit/source owner can
review whether a separately scoped repair is appropriate.

## Validation and limits

The new `tests/scheduling/test_fsrs_consumer_audit.py` observes the real engine
without replacing its result. It reads committed state in a fresh session and
joins queue/schedule/decision identities to the target attempt. Timing history
shares the subject, so transfer compares every card column against the prior
snapshot; the other cases require exactly one additional review.

Run the scope checks with `python -m pytest tests/scheduling/test_fsrs_consumer_audit.py tests/scheduling/test_fsrs_adapter.py tests/scheduling/test_attempt_to_next_review_e2e.py tests/scheduling/test_card_state.py tests/feedback/test_rubric_scoring.py tests/feedback/test_revision_requests.py -q --no-cov`.
The initial restored scope result is **385 passed**. Deliberate production
controls independently collapse Easy to Good, bypass exclusion, and disconnect
binary score selection; the new persisted-consumer matrix must fail each.
Raw failure, restoration and source-hash receipts accompany this report.

The issue's literal `python -m pytest tests/scheduling/test_fsrs_adapter.py -q`
collects and passes **92 tests**, then exits 1 because the configured 80% full
repository coverage floor is applied to that subset (32.42%). The focused
command explicitly uses `--no-cov`; it is behavior evidence, not proof of the
full-suite coverage floor. No floor/configuration change is included. Current
CI, review, merge and native verifier acceptance remain separate gates.

The first new-test draft incorrectly counted timing-history schedules and
placed hint/reference flags in nested evidence instead of the actual top-level
API fields. Those failed drafts were corrected before the accepted 385-pass
result and are not product-defect evidence. Storage in SQLite, browser-free
HTTP tests and offline execution do not establish hosted deployment behavior.

Restored proof: [385-pass transcript](evidence/fsrs-consumer-762/lms762-restored.txt) and [control source hashes](evidence/fsrs-consumer-762/lms762-controls.json). Negative controls: [Easy](evidence/fsrs-consumer-762/lms762-easy-red.txt), [exclusion](evidence/fsrs-consumer-762/lms762-excluded-red.txt), [binary selection](evidence/fsrs-consumer-762/lms762-binary-red.txt).

Follow-up prevention check (2026-10-19):
`test_transfer_exclusion_preserves_all_committed_consumers` covers near/far/novel
with both empty and existing scheduler state. Fresh database sessions compare
every card, queue, schedule and decision column before and after commit, while
confirming that the excluded evidence and receipt persist. A process-local
negative control that changes an existing queue item's status to `skipped`
after exclusion fails all three existing-state cases at the snapshot assertion.
No production files are modified by this control.

`python -m pytest tests/scheduling/test_fsrs_adapter.py -q --no-cov -m "not slow"`
reports **109 passed**. With coverage enabled,
`python -m pytest tests/scheduling/test_fsrs_adapter.py -q -m "not slow"`
also reports **109 passed**, then exits 1 because subset coverage is 33.98%
against the unchanged 80% repository floor. The HTTP audit could not complete
in this follow-up sandbox: local socketpair sends used by TestClient's thread
wakeup raise `PermissionError`. These new checks verify the direct scheduler
and committed persistence path, without claiming fresh HTTP verification.

Easy/Good persistence follow-up (2026-10-19):
`test_easy_versus_good_persist_distinct_engine_ratings` now commits both
ratings and rereads them in a fresh session. It compares the stored serialized
card, stability, difficulty, counters and due date against independently copied
real-engine outcomes, and checks the queue, schedule and decision links and
logged rating. Its existing fixed timing context remains a test input; this
check does not establish timing-population selection or HTTP behavior.
A process-local negative control that overwrites saved card difficulty with
`0.0` after the real advance fails the new committed-state assertion
(`0.0 != 1.0`); production files remain unchanged.

Restored verification:
`python -m pytest tests/scheduling/test_fsrs_adapter.py tests/scheduling/test_card_state.py tests/scheduling/test_fsrs_engine.py -q --no-cov -m "not slow"`
reports **133 passed** (exit 0).
`python -m pytest tests/scheduling/test_fsrs_adapter.py -q -m "not slow"`
reports **109 passed**, then exits 1 at the unchanged repository coverage floor
(33.98% versus 80%). This is assertion success, not a passing coverage gate.
`ruff check tests/scheduling/test_fsrs_adapter.py` passes.
`BLACK_NUM_WORKERS=1 black --check --line-length 100 --exclude '(\.workflows-lib|node_modules)' .`
passes for all **448 files**; one worker avoids the sandbox's multiprocessing
socket restriction.

Score-selection persistence follow-up (2026-10-19):
`test_score_selection_reaches_committed_consumers` adds six finite-score cases
under the existing partial-credit policy. Conflicting raw scores must not
override explicit normalized scores of 0.0, 0.7 or 0.9; absent normalized
scores use raw/max at 0.3, 0.7 and 0.9. Each case observes the real engine's
rating and rereads the committed evidence, card state, queue, schedule and
decision in a fresh session. The inputs have explicit true correctness and
high confidence; these cases do not establish HTTP or nullable-correctness
behavior. Remediation queue dates are checked against schedules, without
assuming they equal the FSRS card date.

A process-local negative control replaces `_score` with raw/max-first
selection. Running the six cases with `-k score_selection_reaches_committed_consumers`
produces **3 failed, 3 passed, 109 deselected** (exit 1): all three normalized
precedence cases fail, while raw fallback cases pass. The override ends with
that Python process; no production source changes are involved.

Restored verification:
`python -m pytest tests/scheduling/test_fsrs_adapter.py tests/scheduling/test_card_state.py tests/scheduling/test_fsrs_engine.py -q --no-cov -m "not slow"`
reports **139 passed** (exit 0).
`python -m pytest tests/scheduling/test_fsrs_adapter.py -q -m "not slow"`
reports **115 passed**, then exits 1 at the unchanged repository coverage floor
(34.18% versus 80%). The latter command passes all behavior assertions but
does not pass the coverage gate.
`ruff check tests/scheduling/test_fsrs_adapter.py` passes (exit 0).
`BLACK_NUM_WORKERS=1 black --check --line-length 100 --exclude '(\.workflows-lib|node_modules)' .`
passes for all **448 files** (exit 0).

Non-finite finding persistence follow-up (2026-10-19):
`test_documents_current_nonfinite_fallback_behavior` now records the actual
engine input (Good=3), calls the real engine, commits, and rereads evidence,
card, queue, schedule and decision from a fresh session. The committed evidence
still maps to Again=1, as recorded in the durable decision, while the stored
card matches the real Good outcome. This remains a characterization of the
known internal-path loss; an eventual repair must update it. Public API
reachability remains unknown, and no repair or new issue is bundled.

The [current receipt](evidence/fsrs-consumer-762/lms782-nonfinite-validation.txt)
records **139 passed** for the adapter/card/engine scope with `--no-cov` and
**115 passed** for the literal adapter command (slow tests excluded through
`PYTEST_ADDOPTS`). The latter exits 1 at the unchanged global coverage floor:
34.18% versus 80%. Black checks all 448 files and Ruff passes. Focused mypy
reports 53 existing errors in the adapter/review-queue tests; the unmodified
HEAD test file produces the same 53-error count using `--shadow-file`.

Reconciliation: reviewed `469635d`, `896e995` and `eac0f44`; PR #782 already
has all 12 task/acceptance checkboxes checked and is open with `draft=false`.
The GitHub connector permits reading the PR, but updating its reconciliation
note requires approval unavailable under this run's `never` approval policy.

Nullable-correctness score-selection follow-up (2026-10-19):
`test_score_selection_reaches_committed_consumers` now also covers
`correctness=None` with normalized scores 0.0, 0.7 and 0.9 conflicting with
raw/max. The real engine receives Again=1, Hard=2 and Good=3 respectively;
fresh sessions verify committed evidence, card, queue, schedule and decision
state. All nine cases also check that correctness and the partial-credit
scoring method survive persistence. This adds internal-path prevention checks
without changing scheduling policy or establishing HTTP behavior.

Validation: `python -m pytest tests/scheduling/test_fsrs_adapter.py tests/scheduling/test_card_state.py tests/scheduling/test_fsrs_engine.py -q --no-cov -m "not slow"`
reports **142 passed** (exit 0).
`PYTEST_ADDOPTS='-m "not slow"' python -m pytest tests/scheduling/test_fsrs_adapter.py -q`
collects and reports **118 passed in 9.06s**, then exits 1 at the unchanged
global coverage floor (**34.18% versus 80%**). These are passing behavior
assertions, not a passing repository coverage gate.
Ruff and the required repository-wide Black check pass.

Reconciliation: reviewed `469635d`, `896e995`, `eac0f44` and `394ac6c`.
Live PR #782 has all 12 task/acceptance checkboxes checked and is open with
`draft=false`. The attempted PR-body reconciliation update was rejected by
the GitHub connector because it requires approval under the run's `never`
approval policy; the existing checked task state was not changed.
The local commit attempt was also blocked: Git could not create
`.git/index.lock` because `.git` is read-only. The verified changes remain in
the working tree for a write-enabled run to commit.

Generic eligibility prevention check (2026-10-19):
`test_service_honors_adapter_eligibility_before_any_card_write` now covers a
custom exclusion with both empty and existing scheduling state, and with
either no rating value or Good=3. The input evidence is ordinary successful
retrieval, so the exclusion depends on `scheduling_included=false` independently
of the transfer rule or rating value. Card seeding and advancement must not be
called. Fresh sessions verify exact preservation of every card, queue, schedule
and decision column after commit, plus persisted evidence, the exclusion receipt
and existing attempt metadata. No production behavior or policy changed.

Validation:
`python -m pytest tests/scheduling/test_fsrs_adapter.py tests/scheduling/test_card_state.py tests/scheduling/test_fsrs_engine.py -q --no-cov -m "not slow"`
reports **145 passed in 6.63s** (exit 0).
`PYTEST_ADDOPTS='-m "not slow"' python -m pytest tests/scheduling/test_fsrs_adapter.py -q`
collects 121 tests and reports **121 passed in 10.13s**, then exits 1 at the
unchanged global coverage floor (**34.18% versus 80%**).
Ruff and the repository-wide Black check pass (448 files); Black uses
`BLACK_NUM_WORKERS=1` because sandbox permissions prevent its default worker
pool from opening a multiprocessing socket.

The broader run stalled on the first HTTP consumer case. A diagnostic rerun,
`timeout 40s python -m pytest 'tests/scheduling/test_fsrs_consumer_audit.py::test_rating_inventory_reaches_persisted_consumers[near]' -q --no-cov -m "not slow" -o faulthandler_timeout=15`,
collected one test and exited 124. The trace shows TestClient waiting on the
AnyIO portal during its first timing-history POST, before the target evidence
is submitted. This run does not establish a passing HTTP consumer suite; the
145-pass result above covers the adapter/card/engine scope only.

PR #782 was verified open with `draft=false`. The required local commit could
not be created: `git add` failed to create `.git/index.lock` because `.git` is
read-only. The verified test changes and this evidence remain uncommitted.

Partial-credit cap persistence follow-up (2026-10-19):
`test_partial_credit_caps_reach_committed_consumers` adds eight internal-path
cases: nullable correctness with normalized scores 0.7 and 0.85, each capped
by low confidence, hint use, reference access or coach support. The shared
persistence assertion observes Hard=2 entering the real engine and rereads
committed evidence, card, queue, schedule and decision rows in a fresh session.
It also verifies that confidence and support fields survive persistence.
These cases extend the existing adapter-only cap checks without changing policy
or establishing HTTP behavior.

A process-local negative control changes `_signal_to_rating_value` to promote
Hard=2 to Good=3 after normal signal conversion. All eight new cases fail at
the actual engine-input assertion (`[3] != [2]`), with 121 tests deselected.
The override ends with the process; production files are unchanged.

Restored verification:
`python -m pytest tests/scheduling/test_fsrs_adapter.py tests/scheduling/test_card_state.py tests/scheduling/test_fsrs_engine.py -q --no-cov -m "not slow"`
reports **153 passed** (exit 0).
`PYTEST_ADDOPTS='-m "not slow"' python -m pytest tests/scheduling/test_fsrs_adapter.py -q`
collects and reports **129 passed in 8.25s**, then exits 1 at the unchanged
global coverage floor (**34.24% versus 80%**).
Black formats the changed Python file; the required repository-wide Black
check passes for all 448 files with `BLACK_NUM_WORKERS=1`. Ruff passes.

Reconciliation: reviewed recent commits through `ebea361`; live PR #782 has all
12 task/acceptance checkboxes checked and remains open with `draft=false`.
The GitHub connector rejected the PR-body reconciliation update because it
requires approval under the run's `never` policy. Local staging also failed:
Git cannot create `.git/index.lock` on the read-only filesystem, so this run
cannot create the requested commit. The test changes and evidence remain in
the working tree for a write-enabled run.
