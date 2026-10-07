"""Regression coverage for generated dependency, tool cache, and coverage artifacts."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )


def test_generated_dirs_untracked_and_vendored_preserved() -> None:
    """Keep the root install out of Git without hiding the vendored workflow copy."""
    assert not _git("ls-files", "node_modules").stdout.splitlines()
    assert not _git("ls-files", "tests/__pycache__").stdout.splitlines()
    assert _git("ls-files", ".github/scripts/node_modules").stdout.splitlines()

    _git("check-ignore", "--no-index", "--", "node_modules/probe.js")
    vendor_probe = subprocess.run(
        [
            "git",
            "check-ignore",
            "--no-index",
            "--",
            ".github/scripts/node_modules/minimatch/package.json",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert vendor_probe.returncode == 1


def test_tool_caches_and_coverage_artifacts_are_ignored() -> None:
    """Require every probe: check-ignore succeeds even when only one path is ignored."""
    paths = [
        ".mypy_cache/probe",
        ".pytest_cache/probe",
        ".ruff_cache/probe",
        "coverage.xml",
        ".coverage",
    ]
    result = _git("check-ignore", "--no-index", "--", *paths)
    assert result.stdout.splitlines() == paths
