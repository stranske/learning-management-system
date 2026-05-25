# Local check targets. These mirror the reusable CI invocations in
# stranske/Workflows/.github/workflows/reusable-10-ci-python.yml so that
# `make check` exercises the same commands the template-provided ci.yml runs.
#
# Usage:
#   make install        # install runtime + dev extras into the active env
#   make lint           # ruff check (matches CI)
#   make format-check   # black --check (matches CI)
#   make format         # black (apply fixes)
#   make typecheck      # mypy on src (matches CI)
#   make test           # pytest with coverage (matches CI)
#   make check          # lint + format-check + typecheck + test

PYTHON ?= python
RUFF ?= ruff
BLACK ?= black
MYPY ?= mypy
PYTEST ?= pytest

RUFF_EXCLUDES := --extend-exclude .workflows-lib
BLACK_EXCLUDES := --exclude '(\.venv|\.workflows-lib|node_modules)'

.PHONY: install lint format format-check typecheck test check clean

install:
	$(PYTHON) -m pip install -e ".[dev]"

lint:
	$(RUFF) check $(RUFF_EXCLUDES) .

format-check:
	$(BLACK) --check --line-length 100 $(BLACK_EXCLUDES) .

format:
	$(BLACK) --line-length 100 $(BLACK_EXCLUDES) .
	$(RUFF) check --fix $(RUFF_EXCLUDES) .

typecheck:
	$(MYPY) --config-file pyproject.toml --exclude .workflows-lib src

test:
	$(PYTEST)

check: lint format-check typecheck test

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage coverage.xml
