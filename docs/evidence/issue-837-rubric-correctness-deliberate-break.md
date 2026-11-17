# Deliberate-break evidence for #837 (rubric evidence correctness)

Relates to issue #837 and PR branch `cursor/issue-837`. This documents the
executed fail-to-restore cycle for threshold-derived rubric `correctness` in
`score_attempt_with_rubric`.

## Break (temporary, not committed)

In `src/lms/feedback/scoring.py`, temporarily restore threshold-derived correctness
on the evidence row:

```diff
-        correctness=None,
+        correctness=normalized_score >= feedback_threshold,
```

Default `feedback_threshold` is `0.85`, so normalized scores `0.50` and `0.84`
become `correctness=False` and FSRS maps them to Again (`rating_value=1`) instead of
Hard (`2`).

## Named failing test

Command:

```bash
python3 -m pytest tests/scheduling/test_runtime_wiring.py::test_rubric_scores_map_to_fsrs_bands -q --no-cov
```

Observed failure (2026-11-17 keepalive verification):

```text
FAILED ...[0.49-1-partial-under-half] - assert False is None  (null-correctness assertion)
FAILED ...[0.5-2-partial-under-mastery] - assert 1 == 2
FAILED ...[0.84-2-partial-under-mastery] - assert 1 == 2
FAILED ...[0.85-3-partial-at-mastery] - assert True is None  (null-correctness assertion)
4 failed in 0.86s
```

The `0.50` and `0.84` cases are the scheduling regression called out in the issue:
partial credit below the feedback threshold must not be treated as binary failure
for FSRS when `normalized_score` still maps to the partial-under-mastery band.

## Restore

Restore `correctness=None` in `src/lms/feedback/scoring.py`, then rerun:

```bash
python3 -m pytest tests/scheduling/test_runtime_wiring.py::test_rubric_scores_map_to_fsrs_bands -q --no-cov
```

Observed restored pass (2026-11-17):

```text
collected 4 items
tests/scheduling/test_runtime_wiring.py ....                               [100%]
============================== 4 passed in 0.71s ===============================
```

Full wiring file after restore:

```bash
python3 -m pytest tests/scheduling/test_runtime_wiring.py -q --no-cov
```

```text
============================== 13 passed in 2.04s ==============================
```

## Acceptance mapping

- Guard location: `src/lms/feedback/scoring.py` (`create_evidence_record` call in
  `score_attempt_with_rubric`).
- Named regression gate:
  `tests/scheduling/test_runtime_wiring.py::test_rubric_scores_map_to_fsrs_bands`
- The deliberate break proves that reintroducing
  `correctness=normalized_score >= feedback_threshold` makes unassisted `0.50` and
  `0.84` rubric scores schedule as Again and fail the band-mapping test.

<!-- deliberate-break: test=tests/scheduling/test_runtime_wiring.py::test_rubric_scores_map_to_fsrs_bands test-file=tests/scheduling/test_runtime_wiring.py break-file=src/lms/feedback/scoring.py command=python3 -m pytest tests/scheduling/test_runtime_wiring.py::test_rubric_scores_map_to_fsrs_bands -q --no-cov -->