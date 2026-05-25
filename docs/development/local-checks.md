# Local checks

The reusable CI workflow at
`stranske/Workflows/.github/workflows/reusable-10-ci-python.yml@main`
runs Ruff, Black, mypy, and pytest with coverage on Python 3.12 and 3.13.
The repo's `Makefile` mirrors those invocations so the same commands work
locally.

## Setup

```bash
python -m venv .venv
. .venv/bin/activate
make install
```

`make install` runs `pip install -e ".[dev]"`, which pulls the runtime
dependencies plus the dev extras (Ruff, Black, mypy, pytest, pytest-cov,
httpx).

## Commands

| Target              | Command                                                         | Notes                                              |
| ------------------- | --------------------------------------------------------------- | -------------------------------------------------- |
| `make lint`         | `ruff check --extend-exclude .workflows-lib .`                  | Same flag set as CI.                               |
| `make format-check` | `black --check --line-length 100 ...`                           | Read-only check matching CI.                       |
| `make format`       | `black ...` then `ruff check --fix ...`                         | Apply formatting and lint autofixes locally.       |
| `make typecheck`    | `mypy --config-file pyproject.toml --exclude .workflows-lib src` | Reads strict settings from `pyproject.toml`.       |
| `make test`         | `pytest`                                                        | Uses `[tool.pytest.ini_options]` and coverage cfg. |
| `make check`        | lint + format-check + typecheck + test                          | The single command to run before pushing.          |

`make check` finishes well under two minutes on a clean checkout of the
M0/M1 surface; it scales linearly with new code as later milestones land.

## Coverage minimum

`[tool.coverage.report]` sets `fail_under = 80`, which matches the template
default (`coverage-min: '80'` in `.github/workflows/ci.yml`). Any future
deviation from 80% should be documented here so reviewers can see why.

## CI parity

The `Makefile` does not author or replace any CI workflow files. The
template-provided `.github/workflows/ci.yml` is the single source of truth
for what CI runs; the Makefile only re-issues the same tool invocations so
local development matches the centralized pipeline. If the reusable
workflow changes its invocation flags, update the Makefile here so the two
stay aligned.
