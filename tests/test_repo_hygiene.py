"""Regression coverage for root-only generated dependency artifacts."""

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
