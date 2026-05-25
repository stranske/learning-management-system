from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_module():
    script_path = Path("scripts/verify_consumer_template_diff.py")
    spec = importlib.util.spec_from_file_location("verify_consumer_template_diff", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_run_check_reports_unavailable_sources(tmp_path):
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
