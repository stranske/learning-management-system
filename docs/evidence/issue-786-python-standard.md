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
