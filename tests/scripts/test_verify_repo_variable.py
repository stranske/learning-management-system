from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


def _load_module() -> ModuleType:
    script_path = Path("scripts/verify_repo_variable.py")
    spec = importlib.util.spec_from_file_location("verify_repo_variable", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_verify_variable_passes_when_name_and_value_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mod = _load_module()

    def _fake_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='[{"name":"USE_CONSOLIDATED_WORKFLOWS","value":"true"}]',
            stderr="",
        )

    monkeypatch.setattr(mod.subprocess, "run", _fake_run)
    mod.verify_variable("owner/repo", "USE_CONSOLIDATED_WORKFLOWS", "true")


def test_verify_variable_fails_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _load_module()

    def _fake_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='[{"name":"OTHER","value":"true"}]',
            stderr="",
        )

    monkeypatch.setattr(mod.subprocess, "run", _fake_run)

    with pytest.raises(mod.RepoVariableValidationError, match="was not found"):
        mod.verify_variable("owner/repo", "USE_CONSOLIDATED_WORKFLOWS", "true")


def test_verify_variable_fails_when_value_differs(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _load_module()

    def _fake_run(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='[{"name":"USE_CONSOLIDATED_WORKFLOWS","value":"false"}]',
            stderr="",
        )

    monkeypatch.setattr(mod.subprocess, "run", _fake_run)

    with pytest.raises(mod.RepoVariableValidationError, match="expected `true`"):
        mod.verify_variable("owner/repo", "USE_CONSOLIDATED_WORKFLOWS", "true")
