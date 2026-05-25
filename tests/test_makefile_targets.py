"""Smoke checks for the Makefile exposed by issue #7.

These tests assert that the Makefile keeps the canonical local-check targets
(`lint`, `format-check`, `format`, `typecheck`, `test`, `check`). If the
Makefile is ever rewritten with new target names, update the
`docs/development/local-checks.md` table and these assertions together.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MAKEFILE = REPO_ROOT / "Makefile"

REQUIRED_TARGETS = ("lint", "format-check", "format", "typecheck", "test", "check")


def _read_makefile() -> str:
    assert MAKEFILE.is_file(), "Makefile must exist at repo root"
    return MAKEFILE.read_text(encoding="utf-8")


def test_makefile_declares_required_targets() -> None:
    text = _read_makefile()
    phony_lines = [line for line in text.splitlines() if line.startswith(".PHONY:")]
    assert phony_lines, ".PHONY declaration is required so targets are not skipped"
    declared = " ".join(line.split(":", 1)[1] for line in phony_lines).split()
    for target in REQUIRED_TARGETS:
        assert target in declared, f"missing .PHONY target: {target}"


def test_makefile_targets_have_recipes_or_deps() -> None:
    """Each target must either have a recipe line or list prerequisite targets."""
    text = _read_makefile()
    for target in REQUIRED_TARGETS:
        body_pattern = rf"^{re.escape(target)}:\s*[^\n]*\n(\t[^\n]+\n)+"
        deps_pattern = rf"^{re.escape(target)}:\s+\S"
        has_body = bool(re.search(body_pattern, text, flags=re.MULTILINE))
        has_deps = bool(re.search(deps_pattern, text, flags=re.MULTILINE))
        assert has_body or has_deps, f"target '{target}' has neither a recipe nor prerequisites"


def test_check_target_runs_full_suite() -> None:
    """`make check` must run every individual gate so it stays the single command."""
    text = _read_makefile()
    match = re.search(r"^check:\s*(.+)$", text, flags=re.MULTILINE)
    assert match, "check: line not found"
    deps = match.group(1).split()
    for required in ("lint", "format-check", "typecheck", "test"):
        assert required in deps, f"`make check` must depend on {required}"
