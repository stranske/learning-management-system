"""Command line entry point for LMS development utilities."""

from __future__ import annotations

import argparse
from pathlib import Path

from lms.research_registry import ResearchRegistryError, load_registry


def main() -> None:
    """Run an LMS CLI command."""
    parser = argparse.ArgumentParser(prog="lms")
    subparsers = parser.add_subparsers(dest="command")

    validate_parser = subparsers.add_parser(
        "validate-research-registry",
        help="validate docs/research/registry YAML files",
    )
    validate_parser.add_argument(
        "--registry-dir",
        type=Path,
        default=None,
        help="directory containing principles.yml, claims.yml, and evidence-sources.yml",
    )

    args = parser.parse_args()
    if args.command == "validate-research-registry":
        try:
            registry = load_registry(args.registry_dir)
        except ResearchRegistryError as exc:
            raise SystemExit(f"research registry validation failed: {exc}") from exc
        print(
            "research registry valid: "
            f"{len(registry.principles)} principles, "
            f"{len(registry.claims)} claims, "
            f"{len(registry.evidence_sources)} evidence sources"
        )
        return

    _run_dev_server()


def _run_dev_server() -> None:
    """Run the FastAPI app under uvicorn for local development."""
    import uvicorn

    uvicorn.run(
        "lms.main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
    )


if __name__ == "__main__":
    main()
