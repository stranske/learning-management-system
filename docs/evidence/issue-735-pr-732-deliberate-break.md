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
uv run pytest tests/test_gate_commit_status_fork_tolerance.py --no-cov
```

Observed output and exit status: exit `1`.

```text
============================= test session starts ==============================
platform darwin -- Python 3.12.2, pytest-9.1.1, pluggy-1.6.0 -- /opt/anaconda3/bin/python
cachedir: .pytest_cache
hypothesis profile 'default'
rootdir: /Users/teacher/.codex/automations/pd-workloop-resume/worktrees/learning-management-system-issue-735
configfile: pyproject.toml
plugins: langsmith-0.10.9, cov-7.1.0, xdist-3.8.0, rerunfailures-16.3, datadir-1.8.0, typeguard-4.5.1, asyncio-1.3.0, pytest_httpserver-1.1.3, hypothesis-6.155.7, regressions-2.11.0, Faker-40.39.0, anyio-4.13.0
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 13 items

tests/test_gate_commit_status_fork_tolerance.py::test_fork_read_only_403_does_not_fail_the_gate FAILED [  7%]
tests/test_gate_commit_status_fork_tolerance.py::test_fork_read_only_403_reports_the_real_verdict FAILED [ 15%]
tests/test_gate_commit_status_fork_tolerance.py::test_fork_read_only_403_preserves_failure_verdict FAILED [ 23%]
tests/test_gate_commit_status_fork_tolerance.py::test_fork_read_only_403_fails_closed_for_other_non_success_verdicts[error] FAILED [ 30%]
tests/test_gate_commit_status_fork_tolerance.py::test_fork_read_only_403_fails_closed_for_other_non_success_verdicts[pending] FAILED [ 38%]
tests/test_gate_commit_status_fork_tolerance.py::test_deleted_fork_read_only_403_reports_the_verdict FAILED [ 46%]
tests/test_gate_commit_status_fork_tolerance.py::test_same_repo_403_still_fails_the_gate PASSED [ 53%]
tests/test_gate_commit_status_fork_tolerance.py::test_rate_limit_403_keeps_its_own_path PASSED [ 61%]
tests/test_gate_commit_status_fork_tolerance.py::test_rate_limit_403_fails_closed_for_non_success_verdicts[failure] PASSED [ 69%]
tests/test_gate_commit_status_fork_tolerance.py::test_rate_limit_403_fails_closed_for_non_success_verdicts[error] PASSED [ 76%]
tests/test_gate_commit_status_fork_tolerance.py::test_rate_limit_403_fails_closed_for_non_success_verdicts[pending] PASSED [ 84%]
tests/test_gate_commit_status_fork_tolerance.py::test_non_403_errors_still_fail_the_gate PASSED [ 92%]
tests/test_gate_commit_status_fork_tolerance.py::test_successful_status_write_is_silent PASSED [100%]

=================================== FAILURES ===================================
________________ test_fork_read_only_403_does_not_fail_the_gate ________________

outcomes = {'fork_read_only': {'failures': [], 'warnings': [], 'summaryWrites': 0, 'summaryRaw': [], ...}, 'fork_read_only_failur...: [], ...}, 'fork_read_only_pending': {'failures': [], 'warnings': [], 'summaryWrites': 0, 'summaryRaw': [], ...}, ...}

    def test_fork_read_only_403_does_not_fail_the_gate(outcomes: dict[str, Any]) -> None:
>       assert outcomes["fork_read_only"]["threw"] is None
E       AssertionError: assert {'status': 403, 'message': 'Resource not accessible by integration'} is None

tests/test_gate_commit_status_fork_tolerance.py:225: AssertionError
_______________ test_fork_read_only_403_reports_the_real_verdict _______________

outcomes = {'fork_read_only': {'failures': [], 'warnings': [], 'summaryWrites': 0, 'summaryRaw': [], ...}, 'fork_read_only_failur...: [], ...}, 'fork_read_only_pending': {'failures': [], 'warnings': [], 'summaryWrites': 0, 'summaryRaw': [], ...}, ...}

    def test_fork_read_only_403_reports_the_real_verdict(outcomes: dict[str, Any]) -> None:
        case = outcomes["fork_read_only"]
        warning = " ".join(case["warnings"])
        summary = " ".join(case["summaryRaw"])
>       assert "read-only" in warning
E       AssertionError: assert 'read-only' in ''

tests/test_gate_commit_status_fork_tolerance.py:233: AssertionError
______________ test_fork_read_only_403_preserves_failure_verdict _______________

outcomes = {'fork_read_only': {'failures': [], 'warnings': [], 'summaryWrites': 0, 'summaryRaw': [], ...}, 'fork_read_only_failur...: [], ...}, 'fork_read_only_pending': {'failures': [], 'warnings': [], 'summaryWrites': 0, 'summaryRaw': [], ...}, ...}

    def test_fork_read_only_403_preserves_failure_verdict(
        outcomes: dict[str, Any],
    ) -> None:
        case = outcomes["fork_read_only_failure"]
        warning = " ".join(case["warnings"])
        summary = " ".join(case["summaryRaw"])
>       assert case["threw"] is None
E       AssertionError: assert {'status': 403, 'message': 'Resource not accessible by integration'} is None

tests/test_gate_commit_status_fork_tolerance.py:247: AssertionError
__ test_fork_read_only_403_fails_closed_for_other_non_success_verdicts[error] __

outcomes = {'fork_read_only': {'failures': [], 'warnings': [], 'summaryWrites': 0, 'summaryRaw': [], ...}, 'fork_read_only_failur...: [], ...}, 'fork_read_only_pending': {'failures': [], 'warnings': [], 'summaryWrites': 0, 'summaryRaw': [], ...}, ...}
state = 'error'

    @pytest.mark.parametrize("state", ["error", "pending"])
    def test_fork_read_only_403_fails_closed_for_other_non_success_verdicts(
        outcomes: dict[str, Any], state: str
    ) -> None:
        case = outcomes[f"fork_read_only_{state}"]
>       assert case["threw"] is None
E       AssertionError: assert {'status': 403, 'message': 'Resource not accessible by integration'} is None

tests/test_gate_commit_status_fork_tolerance.py:259: AssertionError
_ test_fork_read_only_403_fails_closed_for_other_non_success_verdicts[pending] _

outcomes = {'fork_read_only': {'failures': [], 'warnings': [], 'summaryWrites': 0, 'summaryRaw': [], ...}, 'fork_read_only_failur...: [], ...}, 'fork_read_only_pending': {'failures': [], 'warnings': [], 'summaryWrites': 0, 'summaryRaw': [], ...}, ...}
state = 'pending'

    @pytest.mark.parametrize("state", ["error", "pending"])
    def test_fork_read_only_403_fails_closed_for_other_non_success_verdicts(
        outcomes: dict[str, Any], state: str
    ) -> None:
        case = outcomes[f"fork_read_only_{state}"]
>       assert case["threw"] is None
E       AssertionError: assert {'status': 403, 'message': 'Resource not accessible by integration'} is None

tests/test_gate_commit_status_fork_tolerance.py:259: AssertionError
_____________ test_deleted_fork_read_only_403_reports_the_verdict ______________

outcomes = {'fork_read_only': {'failures': [], 'warnings': [], 'summaryWrites': 0, 'summaryRaw': [], ...}, 'fork_read_only_failur...: [], ...}, 'fork_read_only_pending': {'failures': [], 'warnings': [], 'summaryWrites': 0, 'summaryRaw': [], ...}, ...}

    def test_deleted_fork_read_only_403_reports_the_verdict(
        outcomes: dict[str, Any],
    ) -> None:
        case = outcomes["deleted_fork_read_only"]
        warning = " ".join(case["warnings"])
>       assert case["threw"] is None
E       AssertionError: assert {'status': 403, 'message': 'Resource not accessible by integration'} is None

tests/test_gate_commit_status_fork_tolerance.py:269: AssertionError
=========================== short test summary info ============================
FAILED tests/test_gate_commit_status_fork_tolerance.py::test_fork_read_only_403_does_not_fail_the_gate
FAILED tests/test_gate_commit_status_fork_tolerance.py::test_fork_read_only_403_reports_the_real_verdict
FAILED tests/test_gate_commit_status_fork_tolerance.py::test_fork_read_only_403_preserves_failure_verdict
FAILED tests/test_gate_commit_status_fork_tolerance.py::test_fork_read_only_403_fails_closed_for_other_non_success_verdicts[error]
FAILED tests/test_gate_commit_status_fork_tolerance.py::test_fork_read_only_403_fails_closed_for_other_non_success_verdicts[pending]
FAILED tests/test_gate_commit_status_fork_tolerance.py::test_deleted_fork_read_only_403_reports_the_verdict
========================= 6 failed, 7 passed in 3.06s ==========================
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
$ git diff --check origin/main...HEAD
$ echo $?
0
```

No deliberate-break workflow or test change remains in the branch.
