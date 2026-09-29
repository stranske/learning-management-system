# Issue #735: PR #732 fork Gate deliberate-break replay

This is a fresh replay on current `main` at `6fe2644f78da12a8df757fc538e02fd00936fc8e`, not reconstructed output from merged PR #732. The final deliverable changes documentation only.

## Baseline

Command:

```text
uv run pytest tests/test_gate_commit_status_fork_tolerance.py -q --no-cov
```

Observed output:

```text
collected 13 items

tests/test_gate_commit_status_fork_tolerance.py .............            [100%]

============================== 13 passed in 0.36s ==============================
```

## RED: disable only the fork read-only fallback

The deliberate break replaced only this production expression in `.github/workflows/pr-00-gate.yml`:

```diff
-              const readOnlyForkToken =
-                error?.status === 403 && isForkPullRequest && !hitRateLimit;
+              const readOnlyForkToken = false;
```

Command:

```text
uv run pytest tests/test_gate_commit_status_fork_tolerance.py -q --no-cov
```

Observed output and exit status: exit `1`.

```text
collected 13 items

tests/test_gate_commit_status_fork_tolerance.py FFFFFF.......            [100%]

=================================== FAILURES ===================================
________________ test_fork_read_only_403_does_not_fail_the_gate ________________
E       AssertionError: assert {'status': 403, 'message': 'Resource not accessible by integration'} is None

_______________ test_fork_read_only_403_reports_the_real_verdict _______________
E       AssertionError: assert 'read-only' in ''

______________ test_fork_read_only_403_preserves_failure_verdict _______________
E       AssertionError: assert {'status': 403, 'message': 'Resource not accessible by integration'} is None

__ test_fork_read_only_403_fails_closed_for_other_non_success_verdicts[error] __
E       AssertionError: assert {'status': 403, 'message': 'Resource not accessible by integration'} is None

_ test_fork_read_only_403_fails_closed_for_other_non_success_verdicts[pending] _
E       AssertionError: assert {'status': 403, 'message': 'Resource not accessible by integration'} is None

_____________ test_deleted_fork_read_only_403_reports_the_verdict ______________
E       AssertionError: assert {'status': 403, 'message': 'Resource not accessible by integration'} is None

=========================== short test summary info ============================
FAILED tests/test_gate_commit_status_fork_tolerance.py::test_fork_read_only_403_does_not_fail_the_gate
FAILED tests/test_gate_commit_status_fork_tolerance.py::test_fork_read_only_403_reports_the_real_verdict
FAILED tests/test_gate_commit_status_fork_tolerance.py::test_fork_read_only_403_preserves_failure_verdict
FAILED tests/test_gate_commit_status_fork_tolerance.py::test_fork_read_only_403_fails_closed_for_other_non_success_verdicts[error]
FAILED tests/test_gate_commit_status_fork_tolerance.py::test_fork_read_only_403_fails_closed_for_other_non_success_verdicts[pending]
FAILED tests/test_gate_commit_status_fork_tolerance.py::test_deleted_fork_read_only_403_reports_the_verdict
========================= 6 failed, 7 passed in 0.48s ==========================
```

The six failures are confined to fork and deleted-fork read-only-token behavior, which is the regression the issue names.

## GREEN: exact restoration

The workflow expression was restored byte-for-byte and the same command was rerun.

```text
collected 13 items

tests/test_gate_commit_status_fork_tolerance.py .............            [100%]

============================== 13 passed in 0.33s ==============================
```

Restoration check:

```text
$ git diff --exit-code HEAD -- .github/workflows/pr-00-gate.yml tests/test_gate_commit_status_fork_tolerance.py
$ echo $?
0
```

No deliberate-break workflow or test change remains in the branch.
