"""Command line entry point for LMS development utilities."""

from __future__ import annotations

import argparse
from pathlib import Path

from lms.db.session import session_scope
from lms.importers.markdown import import_markdown_notes
from lms.research_registry import ResearchRegistryError, load_registry
from lms.sources.repository import scan_source_references


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
    source_parser = subparsers.add_parser(
        "source-references",
        help="manage source reference records",
    )
    source_subparsers = source_parser.add_subparsers(dest="source_references_command")
    scan_parser = source_subparsers.add_parser(
        "scan-drift",
        help="mark changed markdown file references as stale or missing",
    )
    scan_parser.add_argument(
        "--base-path",
        type=Path,
        default=Path.cwd(),
        help="base path used to resolve relative markdown stable locators",
    )
    scan_parser.add_argument(
        "--actor-id",
        default="system:drift-scan",
        help="actor id recorded in audit events created by the scan",
    )
    import_parser = subparsers.add_parser(
        "import-notes",
        help="import Markdown notes into draft knowledge graph records",
    )
    import_parser.add_argument("path", type=Path, help="Markdown file or directory to import")
    import_parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="maximum number of heading sections to import",
    )
    import_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print planned creates without writing records",
    )
    import_parser.add_argument(
        "--scope",
        choices=("personal", "institutional"),
        default="personal",
        help="ownership scope assigned to imported nodes and edges",
    )
    import_parser.add_argument(
        "--source-visibility",
        choices=("public", "local-only"),
        default="local-only",
        help="visibility assigned to heading-level source references",
    )
    import_parser.add_argument(
        "--actor-id",
        default="system:import-notes",
        help="actor id recorded in import audit events",
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
    if args.command == "source-references":
        if args.source_references_command == "scan-drift":
            with session_scope() as session:
                drift_summary = scan_source_references(
                    session,
                    base_path=args.base_path,
                    actor_id=args.actor_id,
                )
            print(
                "source reference drift scan: "
                f"scanned={drift_summary.scanned} "
                f"current={drift_summary.current} "
                f"stale={drift_summary.stale} "
                f"missing={drift_summary.missing} "
                f"skipped={drift_summary.skipped}"
            )
            return
        parser.error("source-references requires a subcommand")
    if args.command == "import-notes":
        if args.dry_run:
            import_summary = import_markdown_notes(
                None,
                args.path,
                limit=args.limit,
                dry_run=True,
                scope=args.scope,
                source_visibility=args.source_visibility,
                actor_id=args.actor_id,
            )
        else:
            with session_scope() as session:
                import_summary = import_markdown_notes(
                    session,
                    args.path,
                    limit=args.limit,
                    scope=args.scope,
                    source_visibility=args.source_visibility,
                    actor_id=args.actor_id,
                )
        print(import_summary.to_cli_line())
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
