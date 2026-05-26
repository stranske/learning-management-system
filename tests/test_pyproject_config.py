"""Smoke checks for pyproject.toml tool configuration (issue #7).

Validates that the four tool sections required by the CI gate are present and
set to values that will satisfy the template-provided reusable workflow:
  - ruff    : correct target version and line length
  - black   : line-length 100 and at least py312 target
  - mypy    : strict mode enabled
  - pytest  : testpaths declared, coverage fail_under >= 80
"""

from __future__ import annotations

import tomllib
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def _load() -> dict:  # type: ignore[type-arg]
    with PYPROJECT.open("rb") as fh:
        return tomllib.load(fh)


def test_ruff_section_present() -> None:
    data = _load()
    assert "ruff" in data.get("tool", {}), "Missing [tool.ruff]"


def test_ruff_line_length() -> None:
    ruff = _load()["tool"]["ruff"]
    assert ruff.get("line-length") == 100, "ruff line-length must be 100"


def test_ruff_target_version() -> None:
    ruff = _load()["tool"]["ruff"]
    assert ruff.get("target-version") == "py312", "ruff target-version must be py312"


def test_black_section_present() -> None:
    data = _load()
    assert "black" in data.get("tool", {}), "Missing [tool.black]"


def test_black_line_length() -> None:
    black = _load()["tool"]["black"]
    assert black.get("line-length") == 100, "black line-length must be 100"


def test_black_targets_py312() -> None:
    black = _load()["tool"]["black"]
    targets = black.get("target-version", [])
    assert "py312" in targets, "black must target at least py312"


def test_mypy_section_present() -> None:
    data = _load()
    assert "mypy" in data.get("tool", {}), "Missing [tool.mypy]"


def test_mypy_strict_enabled() -> None:
    mypy = _load()["tool"]["mypy"]
    assert mypy.get("strict") is True, "mypy strict must be true"


def test_mypy_has_explicit_package_bases() -> None:
    mypy = _load()["tool"]["mypy"]
    assert mypy.get("explicit_package_bases") is True, "mypy explicit_package_bases must be true"


def test_mypy_files_scope_includes_repo_targets() -> None:
    mypy = _load()["tool"]["mypy"]
    files = mypy.get("files", [])
    assert "src" in files, "mypy files must include 'src'"
    assert "tests" in files, "mypy files must include 'tests'"
    assert "scripts" in files, "mypy files must include 'scripts'"


def test_pytest_section_present() -> None:
    data = _load()
    assert "pytest" in data.get("tool", {}), "Missing [tool.pytest]"


def test_pytest_testpaths_declared() -> None:
    opts = _load()["tool"]["pytest"]["ini_options"]
    assert "tests" in opts.get("testpaths", []), "pytest testpaths must include 'tests'"


def test_pytest_addopts_covers_lms_package() -> None:
    opts = _load()["tool"]["pytest"]["ini_options"]
    addopts = opts.get("addopts", "")
    assert "--cov=lms" in addopts, "pytest addopts must collect coverage for lms package"


def test_coverage_fail_under_at_least_80() -> None:
    report = _load()["tool"]["coverage"]["report"]
    fail_under = report.get("fail_under", 0)
    assert fail_under >= 80, f"coverage fail_under must be >= 80, got {fail_under}"


def test_build_system_does_not_pin_setuptools_min_version() -> None:
    build_system = _load().get("build-system", {})
    requires = build_system.get("requires", [])
    assert "setuptools" in requires, "build-system requires must include setuptools"
    assert all(
        not requirement.startswith("setuptools>=") for requirement in requires
    ), "setuptools should not be min-version pinned to keep offline/editable installs portable"
