#!/usr/bin/env python3
"""Verify a GitHub repository variable matches an expected value."""

from __future__ import annotations

import argparse
import json
import subprocess


class RepoVariableValidationError(ValueError):
    """Raised when a repository variable is missing or has an unexpected value."""


def read_repo_variables(repo: str) -> list[dict[str, str]]:
    result = subprocess.run(
        ["gh", "variable", "list", "--repo", repo, "--json", "name,value"],
        capture_output=True,
        text=True,
        check=True,
    )
    parsed = json.loads(result.stdout or "[]")
    if not isinstance(parsed, list):
        raise RepoVariableValidationError("Unexpected response format from `gh variable list`.")
    return parsed


def verify_variable(repo: str, name: str, expected_value: str) -> None:
    variables = read_repo_variables(repo)
    for item in variables:
        if item.get("name") != name:
            continue
        actual = item.get("value")
        if actual == expected_value:
            return
        raise RepoVariableValidationError(
            f"Variable `{name}` has value `{actual}`, expected `{expected_value}`."
        )
    raise RepoVariableValidationError(f"Variable `{name}` was not found in repo `{repo}`.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify a GitHub repository variable value via `gh variable list`."
    )
    parser.add_argument("--repo", required=True, help="GitHub repo slug, e.g. owner/name")
    parser.add_argument("--name", required=True, help="Variable name to verify")
    parser.add_argument("--expected-value", required=True, help="Expected variable value")
    return parser.parse_args()


def run(args: argparse.Namespace) -> int:
    verify_variable(args.repo, args.name, args.expected_value)
    print(f"Verified `{args.name}`=`{args.expected_value}` for `{args.repo}`.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run(parse_args()))
