#!/usr/bin/env python3
"""Verify consumer-repo files against a local Workflows sync-manifest snapshot.

This script is intended for template parity checks in consumer repos where a local
Workflows checkout (or snapshot) is available under `.workflows-lib`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

SECTION_NAMES = [
    "workflows",
    "prompts",
    "codex_config",
    "scripts",
    "templates",
    "actions",
    "docs",
    "copilot_config",
    "llm_config",
    "git_config",
    "issue_templates",
    "user_docs",
]


@dataclass
class DiffEntry:
    section: str
    source: str
    target: str
    sync_mode: str
    kind: str
    details: str


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def iter_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file())


def _norm_target(entry: dict[str, Any], source: str) -> str:
    return str(entry.get("target", source)).strip()


def check_entry(
    *,
    section: str,
    entry: dict[str, Any],
    template_root: Path,
    consumer_root: Path,
) -> list[DiffEntry]:
    diffs: list[DiffEntry] = []

    source = str(entry.get("source", "")).strip()
    if not source:
        return diffs

    target = _norm_target(entry, source)
    sync_mode = str(entry.get("sync_mode", "overwrite"))
    is_directory = bool(entry.get("is_directory", False))

    source_path = template_root / source
    target_path = consumer_root / target

    if not source_path.exists():
        diffs.append(
            DiffEntry(section, source, target, sync_mode, "missing_template_source", str(source_path))
        )
        return diffs

    if not target_path.exists():
        diffs.append(DiffEntry(section, source, target, sync_mode, "missing_in_consumer", str(target_path)))
        return diffs

    if is_directory:
        sfiles = iter_files(source_path)
        tfiles = iter_files(target_path)
        srel = {p.relative_to(source_path): p for p in sfiles}
        trel = {p.relative_to(target_path): p for p in tfiles}

        missing = sorted(set(srel) - set(trel))
        extra = sorted(set(trel) - set(srel))

        for rel in missing:
            diffs.append(
                DiffEntry(
                    section,
                    source,
                    target,
                    sync_mode,
                    "missing_file_in_directory",
                    str((target_path / rel).as_posix()),
                )
            )

        for rel in extra:
            diffs.append(
                DiffEntry(
                    section,
                    source,
                    target,
                    sync_mode,
                    "extra_file_in_directory",
                    str((target_path / rel).as_posix()),
                )
            )

        for rel in sorted(set(srel) & set(trel)):
            if sha256_file(srel[rel]) != sha256_file(trel[rel]):
                diffs.append(
                    DiffEntry(
                        section,
                        source,
                        target,
                        sync_mode,
                        "content_mismatch",
                        str(rel.as_posix()),
                    )
                )
        return diffs

    if source_path.is_dir() != target_path.is_dir():
        diffs.append(
            DiffEntry(
                section,
                source,
                target,
                sync_mode,
                "type_mismatch",
                f"template_is_dir={source_path.is_dir()}, consumer_is_dir={target_path.is_dir()}",
            )
        )
        return diffs

    if source_path.is_file() and sha256_file(source_path) != sha256_file(target_path):
        diffs.append(DiffEntry(section, source, target, sync_mode, "content_mismatch", target))

    return diffs


def load_manifest(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Manifest is not a mapping: {path}")
    return data


def run_check(template_root: Path, consumer_root: Path, manifest_path: Path) -> dict[str, Any]:
    manifest = load_manifest(manifest_path)

    strict: list[DiffEntry] = []
    create_only: list[DiffEntry] = []

    for section in SECTION_NAMES:
        entries = manifest.get(section, [])
        if not isinstance(entries, list):
            continue

        for raw in entries:
            if not isinstance(raw, dict):
                continue
            for d in check_entry(
                section=section,
                entry=raw,
                template_root=template_root,
                consumer_root=consumer_root,
            ):
                if d.sync_mode == "create_only":
                    create_only.append(d)
                else:
                    strict.append(d)

    unavailable_sources = sum(1 for d in strict + create_only if d.kind == "missing_template_source")

    return {
        "template_root": str(template_root),
        "consumer_root": str(consumer_root),
        "manifest": str(manifest_path),
        "strict_diff_count": len(strict),
        "create_only_diff_count": len(create_only),
        "unavailable_source_count": unavailable_sources,
        "strict_diffs": [d.__dict__ for d in strict],
        "create_only_diffs": [d.__dict__ for d in create_only],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--template-root",
        default=".workflows-lib",
        help="Path to local Workflows snapshot that contains template source files.",
    )
    parser.add_argument(
        "--manifest",
        default=".workflows-lib/.github/sync-manifest.yml",
        help="Path to sync-manifest.yml from the Workflows snapshot.",
    )
    parser.add_argument(
        "--consumer-root",
        default=".",
        help="Path to consumer repository root.",
    )
    parser.add_argument(
        "--report",
        default="",
        help="Optional JSON report output path.",
    )
    parser.add_argument(
        "--ignore-unavailable-source",
        action="store_true",
        help=(
            "Do not fail when template sources are missing from the local snapshot; "
            "still reports those entries in JSON output."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_check(
        template_root=Path(args.template_root),
        consumer_root=Path(args.consumer_root),
        manifest_path=Path(args.manifest),
    )

    if args.report:
        Path(args.report).write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    print(f"strict_diffs={report['strict_diff_count']}")
    print(f"create_only_diffs={report['create_only_diff_count']}")
    print(f"unavailable_sources={report['unavailable_source_count']}")

    strict_diffs = report["strict_diffs"]
    if args.ignore_unavailable_source:
        strict_diffs = [d for d in strict_diffs if d["kind"] != "missing_template_source"]

    return 0 if len(strict_diffs) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
