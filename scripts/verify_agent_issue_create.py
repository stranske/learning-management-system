#!/usr/bin/env python3
"""Validate AGENT_ISSUE_FORMAT body content and optionally run `gh issue create`."""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

REQUIRED_SECTIONS = ("tasks", "acceptance criteria")


class IssueBodyValidationError(ValueError):
    """Raised when the issue body misses required AGENT_ISSUE_FORMAT sections."""


def normalize_sections(markdown: str) -> set[str]:
    """Return lower-cased second-level markdown headings found in the body."""
    return {
        match.group(1).strip().lower()
        for match in re.finditer(r"^##\s+(.+?)\s*$", markdown, re.MULTILINE)
    }


def validate_issue_body(markdown: str) -> None:
    headings = normalize_sections(markdown)
    missing = [section for section in REQUIRED_SECTIONS if section not in headings]
    if missing:
        missing_text = ", ".join(missing)
        raise IssueBodyValidationError(
            f"Issue body is missing required section(s): {missing_text}. "
            "Expected headers like `## Tasks` and `## Acceptance Criteria`."
        )


def build_gh_issue_create_cmd(repo: str, title: str, body_file: Path) -> list[str]:
    return [
        "gh",
        "issue",
        "create",
        "--repo",
        repo,
        "--title",
        title,
        "--body-file",
        str(body_file),
    ]


def run(args: argparse.Namespace) -> int:
    body_text = args.body_file.read_text(encoding="utf-8")
    validate_issue_body(body_text)

    cmd = build_gh_issue_create_cmd(args.repo, args.title, args.body_file)

    if args.dry_run:
        print("Body validation passed.")
        print("Dry run enabled; command not executed:")
        print(" ".join(cmd))
        return 0

    subprocess.run(cmd, check=True)
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify AGENT_ISSUE_FORMAT body content and optionally create a GitHub issue."
    )
    parser.add_argument("--repo", required=True, help="GitHub repo slug, e.g. owner/name")
    parser.add_argument("--title", required=True, help="Issue title")
    parser.add_argument(
        "--body-file",
        type=Path,
        required=True,
        help="Path to markdown file containing the issue body",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and print the gh command without creating an issue",
    )
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
