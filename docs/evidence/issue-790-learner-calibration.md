# Learner calibration acceptance evidence

Verified on 2026-10-26, extending the implementation in `8ea4485`.

- [x] The server-rendered `/app/learner/calibration` route uses `LearnerIdDep`,
  which enforces `CurrentUserDep` and learner ownership before computing
  `calibration_for_learner(...).as_dict()`.
- [x] The learner dashboard links to calibration with the resolved learner ID;
  the calibration page links back to that learner's home.
- [x] `tests/ui/test_learner_calibration.py` verifies authenticated access,
  ownership rejection, an empty state, and seeded overconfidence buckets.
- [x] `test_learner_calibration_page_shows_bucket_accuracy` passes with both
  implicit and explicit authenticated learner selection. It verifies five
  scored records at confidence 5/5 yield 20% accuracy and an overconfidence
  flag, excluding another learner's evidence and unscored or unrated records.
- [x] Deliberately clearing the route's buckets makes the named test fail;
  restoring the route makes it pass.

## Deliberate break and restore

Temporarily inserted the following immediately after the report is computed in
`src/lms/ui/api.py::learner_calibration_route`:

```python
report["buckets"] = []
```

Ran the named test with `-m "not slow" --no-cov --tb=short`. Both parametrizations
failed at the expected bucket assertion, with exit code 1:

```text
FAILED test_learner_calibration_page_shows_bucket_accuracy[False]
FAILED test_learner_calibration_page_shows_bucket_accuracy[True]
assert '<th scope="row">5/5</th><td>5</td><td>20%</td>' in response.text
2 failed in 1.03s
```

Removed the temporary assignment. `git diff --quiet -- src/lms/ui/api.py`
confirmed the route was fully restored. The subsequent regression run passed
all 30 tests in 4.20 seconds.

## Verification environment and commands

The installed Python 3.14.8 TestClient stack hangs with its default asyncio
event loop in this sandbox. The installed uvloop event loop successfully ran
the same tests; no application or test configuration was changed to do so.
The passing regression command was:

```bash
python - <<'PY'
import asyncio
import pytest
import uvloop

asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
raise SystemExit(pytest.main([
    'tests/ui/test_learner_calibration.py',
    'tests/ui/test_learner_dashboard.py',
    'tests/ui/test_app_shell.py',
    'tests/analytics/test_calibration.py',
    '-m', 'not slow', '--no-cov',
]))
PY
```

Formatting and lint checks passed:

```bash
black --line-length 100 tests/ui/test_learner_calibration.py
BLACK_NUM_WORKERS=1 black --check --line-length 100 --exclude '(\.workflows-lib|node_modules)' .
ruff check tests/ui/test_learner_calibration.py
git diff --check
```

Black checked all 452 Python files. Its single-worker setting avoids the
sandbox's restriction on the multiprocessing forkserver socket.
