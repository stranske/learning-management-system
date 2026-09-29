# Issue #737: fresh fork Gate deliberate-break evidence

This replay used current `main` commit `f6e59e60bfb16e1177a09162e49b3983c482dfce` on 2026-09-29. It supersedes the earlier transcript in this document, whose command provenance was ambiguous. The workflow in `.github/workflows/pr-00-gate.yml` already runs this exact command for both branches and uploads future replay logs as a CI artifact. The transcript below is a **new local execution**, not a claim that CI wrote back to this tracked document. The only output normalization is the local `rootdir` path, displayed as `<repository-root>`; test output, failures, and exit results are otherwise preserved. `pyproject.toml` supplies `-v` in `addopts`, so the literal `-q` invocation still emits a pytest session header and assertion details.

## Deliberate mutation

Exactly one production expression was temporarily changed:

```diff
diff --git a/.github/workflows/pr-00-gate.yml b/.github/workflows/pr-00-gate.yml
index 1239859..c0109e1 100644
--- a/.github/workflows/pr-00-gate.yml
+++ b/.github/workflows/pr-00-gate.yml
@@ -382,8 +382,7 @@ jobs:
                 baseRepo &&
                   (headRepoObject === null || (headRepo && headRepo !== baseRepo)),
               );
-              const readOnlyForkToken =
-                error?.status === 403 && isForkPullRequest && !hitRateLimit;
+              const readOnlyForkToken = false;
               if (hitRateLimit) {
                 core.warning('Rate limit prevented Gate from updating the commit status.');
                 if (state !== 'success') {
```

Command:

```text
uv run pytest tests/test_gate_commit_status_fork_tolerance.py -q --no-cov
```

Exit status: `1` (six named fork/deleted-fork failures; seven other cases passed).

```text
============================= test session starts ==============================
platform darwin -- Python 3.12.2, pytest-9.1.1, pluggy-1.6.0
rootdir: <repository-root>
configfile: pyproject.toml
plugins: langsmith-0.10.9, cov-7.1.0, xdist-3.8.0, rerunfailures-16.3, datadir-1.8.0, typeguard-4.5.1, asyncio-1.3.0, pytest_httpserver-1.1.3, hypothesis-6.155.7, regressions-2.11.0, Faker-40.39.0, anyio-4.13.0
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collected 13 items

tests/test_gate_commit_status_fork_tolerance.py FFFFFF.......            [100%]

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
========================= 6 failed, 7 passed in 0.52s ==========================
```

## Exact restoration

The original workflow bytes were copied back and compared to the saved original. `git diff --exit-code HEAD -- .github/workflows/pr-00-gate.yml tests/test_gate_commit_status_fork_tolerance.py` exited `0` before the restored test run. The same exact command was run again:

```text
uv run pytest tests/test_gate_commit_status_fork_tolerance.py -q --no-cov
```

Exit status: `0` (13 passed).

```text
============================= test session starts ==============================
platform darwin -- Python 3.12.2, pytest-9.1.1, pluggy-1.6.0
rootdir: <repository-root>
configfile: pyproject.toml
plugins: langsmith-0.10.9, cov-7.1.0, xdist-3.8.0, rerunfailures-16.3, datadir-1.8.0, typeguard-4.5.1, asyncio-1.3.0, pytest_httpserver-1.1.3, hypothesis-6.155.7, regressions-2.11.0, Faker-40.39.0, anyio-4.13.0
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collected 13 items

tests/test_gate_commit_status_fork_tolerance.py .............            [100%]

============================== 13 passed in 0.36s ==============================
```

The test file was never modified. The workflow contains a CI replay job that writes `red.log`, `red.exit`, `green.log`, `green.exit`, `mutation.diff`, and `restoration.diff` to a run-scoped artifact; it does not alter the PR's committed evidence file. This document records the independently observed current-main replay. The separate `git diff --check origin/main...HEAD` acceptance check is a pre-push repository check, not a command within the Gate job.
