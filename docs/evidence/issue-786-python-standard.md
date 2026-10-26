# Python CI execution standard — issue 786

Both repository-owned reusable CI callers now test Python 3.13 and 3.14,
with 3.14 selected as primary and coverage runtime. The remaining standalone
Gate setup step also uses 3.14. The supported application floor and universal
lock-generation floor remain 3.12.

Local validation on 2026-10-26 used `/opt/anaconda3/bin/python3` (Python 3.12.2)
for these standalone YAML tests. The canonical `.venv/bin/python` startup probe
stalled and was terminated; no application-suite result from that environment
is claimed. `--noconftest` isolates these workflow-only tests from application
fixtures and `-o addopts=` disables unrelated application coverage collection.

```sh
python -m pytest tests/test_ci_python_standard.py \
  tests/test_compose_smoke_gate_workflow.py -q --noconftest -o addopts=
# 9 passed
python -m black --check tests/test_ci_python_standard.py
python -m ruff check tests/test_ci_python_standard.py
actionlint -shellcheck= .github/workflows/ci.yml .github/workflows/pr-00-gate.yml
git diff --check
```

Before the workflow edits, the named standard test failed on the two 3.12
matrices and the standalone 3.12 pin; seven parser checks passed. After the
edits, temporarily replacing the CI matrix with `["3.12", "3.14"]` made
`test_workflow_python_pins_follow_standard` fail. Restoring the workflow's
exact bytes returned it to PASS. The guard preserves YAML scalar spelling,
rejects duplicate mappings, and distinguishes 3.120 from 3.12.

Hosted acceptance remains pending: the exact PR head needs passing Python
3.13 and 3.14 Gate legs and the coverage guard. Do not interpret the local
Python 3.12 test result as a Python 3.14 application-suite result. Issue 786
also retains its November 7 remote-pin persistence read.

Follow-up validation on 2026-10-26 used the runner's Python 3.14.8. The guard
now asserts that both standalone Gate setup jobs use exactly 3.14, checks all
six runtime keys against each retired-version representation, and includes
automated matrix break/restoration checks for both CI callers. Mutations use
temporary copies; repository workflows are not edited. Missing annotations
in the original guard caused 14 strict-mypy errors; those are now fixed.

```sh
pytest tests/test_ci_python_standard.py tests/test_compose_smoke_gate_workflow.py \
  -q --no-cov -m 'not slow'
# 40 passed
mypy tests/test_ci_python_standard.py
ruff check tests/test_ci_python_standard.py
BLACK_NUM_WORKERS=1 black --check --line-length 100 --exclude '(\.workflows-lib|node_modules)' .
# 450 files would be left unchanged
```

Black needs one worker because the sandbox disallows its multiprocessing
socket. A local `pytest -q -m 'not slow'` attempt stalled at
`test_calibration_endpoint_surfaces_overconfidence`; an isolated replay also
timed out while entering Starlette's TestClient through AnyIO's blocking
portal. No passing local application-suite result is claimed.

The earlier head `44193d32a6d56a7c98b522f0ba9df09c1aa5a538` has a successful
[Gate run](https://github.com/stranske/learning-management-system/actions/runs/40329255956)
with passing Python 3.13 and 3.14 legs and coverage enforcement. The 3.14 job
reports 2,876 passed, 14 skipped and 92.20% coverage against the 80% minimum.
Those results predate this follow-up; the new head still needs its own Gate
run. Both named workflow files currently have zero lines containing `3.12`;
the dated November 7 persistence read remains pending.

This follow-up remains uncommitted: `.git` is read-only, and both `git add`
and `git commit` fail to create `.git/index.lock`. Attempts to update PR #796's
task checkboxes, add `needs-human`, and post the blocker comment were also
rejected because those connector actions require approval and this run's
approval policy is `never`. PR #796 was verified open and ready for review.
