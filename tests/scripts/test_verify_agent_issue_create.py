from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest


def _load_module() -> ModuleType:
    script_path = Path("scripts/verify_agent_issue_create.py")
    spec = importlib.util.spec_from_file_location("verify_agent_issue_create", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_validate_issue_body_accepts_required_sections() -> None:
    mod = _load_module()
    body = """
## Why
x

## Tasks
- [ ] do x

## Acceptance Criteria
- [ ] done
"""
    mod.validate_issue_body(body)


def test_validate_issue_body_rejects_missing_required_sections() -> None:
    mod = _load_module()
    body = """
## Why
x

## Scope
x
"""

    with pytest.raises(mod.IssueBodyValidationError):
        mod.validate_issue_body(body)


def test_run_dry_run_prints_command(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    mod = _load_module()

    body_file = tmp_path / "body.md"
    body_file.write_text(
        """
## Tasks
- [ ] A

## Acceptance Criteria
- [ ] B
""".strip() + "\n",
        encoding="utf-8",
    )

    args = mod.parse_args.__globals__["argparse"].Namespace(
        repo="stranske/learning-management-system",
        title="dry run check",
        body_file=body_file,
        dry_run=True,
    )

    code = mod.run(args)
    out = capsys.readouterr().out

    assert code == 0
    assert "Body validation passed." in out
    assert "gh issue create" in out
    assert "--repo stranske/learning-management-system" in out
