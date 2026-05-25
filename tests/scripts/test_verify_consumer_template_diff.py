from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from types import SimpleNamespace

import pytest


def _load_module() -> ModuleType:
    script_path = Path("scripts/verify_consumer_template_diff.py")
    spec = importlib.util.spec_from_file_location("verify_consumer_template_diff", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_run_check_reports_unavailable_sources(tmp_path: Path) -> None:
    mod = _load_module()

    template_root = tmp_path / "template"
    consumer_root = tmp_path / "consumer"
    template_root.mkdir()
    consumer_root.mkdir()

    manifest_path = tmp_path / "manifest.yml"
    manifest_path.write_text(
        """
version: 1
workflows:
  - source: .github/workflows/example.yml
""".strip() + "\n",
        encoding="utf-8",
    )

    report = mod.run_check(
        template_root=template_root,
        consumer_root=consumer_root,
        manifest_path=manifest_path,
    )

    assert report["strict_diff_count"] == 1
    assert report["unavailable_source_count"] == 1
    assert report["strict_diffs"][0]["kind"] == "missing_template_source"


def test_run_check_flags_untracked_local_workflow_files(tmp_path: Path) -> None:
    mod = _load_module()

    template_root = tmp_path / "template"
    consumer_root = tmp_path / "consumer"
    template_root.mkdir()
    consumer_root.mkdir()
    (template_root / ".github/workflows").mkdir(parents=True)
    (consumer_root / ".github/workflows").mkdir(parents=True)

    # Expected template workflow file.
    expected = ".github/workflows/agents-verifier.yml"
    (template_root / expected).write_text("name: verifier\n", encoding="utf-8")
    (consumer_root / expected).write_text("name: verifier\n", encoding="utf-8")

    # Local file not tracked in manifest should be reported.
    unexpected = consumer_root / ".github/workflows/local-shadow.yml"
    unexpected.write_text("name: local-shadow\n", encoding="utf-8")

    manifest_path = tmp_path / "manifest.yml"
    manifest_path.write_text(
        f"""
version: 1
workflows:
  - source: {expected}
""".strip() + "\n",
        encoding="utf-8",
    )

    report = mod.run_check(
        template_root=template_root,
        consumer_root=consumer_root,
        manifest_path=manifest_path,
    )

    assert report["strict_diff_count"] == 1
    assert report["strict_diffs"][0]["kind"] == "untracked_workflow_file"
    assert report["strict_diffs"][0]["target"] == ".github/workflows/local-shadow.yml"


def test_main_fails_with_require_create_only_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mod = _load_module()

    template_root = tmp_path / "template"
    consumer_root = tmp_path / "consumer"
    template_root.mkdir()
    consumer_root.mkdir()

    required = "docs/required.md"
    (template_root / "docs").mkdir(parents=True)
    (template_root / required).write_text("required\n", encoding="utf-8")

    manifest_path = tmp_path / "manifest.yml"
    manifest_path.write_text(
        f"""
version: 1
docs:
  - source: {required}
    sync_mode: create_only
""".strip() + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        mod,
        "parse_args",
        lambda: SimpleNamespace(
            template_root=str(template_root),
            consumer_root=str(consumer_root),
            manifest=str(manifest_path),
            report="",
            ignore_unavailable_source=False,
            require_create_only_clean=True,
        ),
    )

    assert mod.main() == 1


def test_main_allows_create_only_diffs_without_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mod = _load_module()

    template_root = tmp_path / "template"
    consumer_root = tmp_path / "consumer"
    template_root.mkdir()
    consumer_root.mkdir()

    required = "docs/required.md"
    (template_root / "docs").mkdir(parents=True)
    (template_root / required).write_text("required\n", encoding="utf-8")

    manifest_path = tmp_path / "manifest.yml"
    manifest_path.write_text(
        f"""
version: 1
docs:
  - source: {required}
    sync_mode: create_only
""".strip() + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        mod,
        "parse_args",
        lambda: SimpleNamespace(
            template_root=str(template_root),
            consumer_root=str(consumer_root),
            manifest=str(manifest_path),
            report="",
            ignore_unavailable_source=False,
            require_create_only_clean=False,
        ),
    )

    assert mod.main() == 0
