"""Command line entry point for LMS development utilities."""

from __future__ import annotations

import argparse
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError

from lms.db.session import session_scope
from lms.demo import build_minimum_demo_smoke_summary, render_minimum_demo_smoke
from lms.export_import import ExportImportError, export_jsonl, export_to_path, import_jsonl
from lms.importers.csv_graph import CsvGraphImportError, import_csv_graph
from lms.importers.markdown import import_markdown_notes
from lms.llm.authoring_assist import ProposalDraft, propose_authoring_drafts
from lms.llm.budgets import DailyBudgetTracker
from lms.llm.client import LLMClient
from lms.llm.config import DEFAULT_MODE_MODELS, LLMConfig
from lms.llm.eval_sets import EvalSetError, load_eval_set, replay_eval_set
from lms.llm.providers import FakeProvider
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
        help=(
            "directory containing principles.yml, claims.yml, evidence-sources.yml, "
            "and optional research-scans.yml / evidence-reviews.yml"
        ),
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
    authoring_assist_parser = subparsers.add_parser(
        "authoring-assist",
        help="LLM-assisted authoring operations",
    )
    authoring_assist_subparsers = authoring_assist_parser.add_subparsers(
        dest="authoring_assist_command"
    )
    propose_parser = authoring_assist_subparsers.add_parser(
        "propose",
        help="create a draft node, edge, and prompt from a source reference",
    )
    propose_parser.add_argument(
        "--source-reference",
        required=True,
        metavar="ID",
        help="stable id of the SourceReference to anchor the proposal",
    )
    propose_parser.add_argument(
        "--target-node",
        required=True,
        metavar="ID",
        help="published KnowledgeNode id to link the proposed node to",
    )
    propose_parser.add_argument(
        "--learning-goal",
        required=True,
        metavar="ID",
        help="LearningGoal id that determines the ownership scope",
    )
    propose_parser.add_argument(
        "--actor-id",
        required=True,
        help="actor id recorded in audit events",
    )
    propose_parser.add_argument(
        "--related-node-title",
        required=True,
        help="title for the proposed KnowledgeNode",
    )
    propose_parser.add_argument(
        "--related-node-knowledge-type",
        required=True,
        help="knowledge type for the proposed node (e.g. conceptual)",
    )
    propose_parser.add_argument(
        "--prompt-body",
        required=True,
        help="body text for the proposed Prompt",
    )
    propose_parser.add_argument(
        "--prompt-knowledge-type",
        required=True,
        help="knowledge type for the proposed prompt",
    )
    propose_parser.add_argument(
        "--prompt-cognitive-action",
        required=True,
        help="intended cognitive action (e.g. explain, recall)",
    )
    propose_parser.add_argument(
        "--prompt-demand-level",
        required=True,
        help="demand level (e.g. low, medium, high)",
    )
    propose_parser.add_argument(
        "--prompt-answer-form",
        required=True,
        help="expected answer form (e.g. short-text)",
    )
    propose_parser.add_argument(
        "--related-node-description",
        default=None,
        help="optional description for the proposed node",
    )
    propose_parser.add_argument(
        "--edge-type",
        default=None,
        help="optional edge type linking the proposed node to the target",
    )
    propose_parser.add_argument(
        "--learner-id",
        default=None,
        help="optional learner id for LLMSession tracking",
    )
    llm_parser = subparsers.add_parser(
        "llm",
        help="LLM client operations (eval replays, etc.)",
    )
    llm_subparsers = llm_parser.add_subparsers(dest="llm_command")
    replay_eval_parser = llm_subparsers.add_parser(
        "replay-eval",
        help="validate a gold-set JSONL file and (optionally) replay it",
    )
    replay_eval_parser.add_argument(
        "path",
        type=Path,
        help="path to the JSONL gold set (e.g. docs/llm/eval-sets/study-coach-v1.jsonl)",
    )
    replay_eval_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate schema and print a per-scenario summary without provider calls",
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
    import_graph_parser = subparsers.add_parser(
        "import-graph",
        help="import knowledge graph nodes and prerequisite edges from CSV",
    )
    import_graph_parser.add_argument("path", type=Path, help="CSV graph file to import")
    import_graph_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate and report counts without writing records",
    )
    import_graph_parser.add_argument(
        "--actor-id",
        default="system:csv-graph-importer",
        help="actor id recorded in audit events created by the import",
    )
    export_parser = subparsers.add_parser(
        "export",
        help="export v1 LMS records as typed JSONL",
    )
    export_parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="JSONL output file; stdout is used when omitted",
    )
    export_parser.add_argument(
        "--include-llm-traces",
        choices=("evidence-grade-only", "all"),
        default="evidence-grade-only",
        help="which LLM session records to include",
    )
    export_parser.add_argument(
        "--include-source-content",
        choices=("public-only", "all"),
        default="public-only",
        help="source body inclusion policy; local-only content is omitted by default",
    )
    export_parser.add_argument(
        "--include-pii",
        choices=("never", "all"),
        default="never",
        help="PII inclusion policy",
    )
    export_parser.add_argument(
        "--yes-i-mean-it",
        action="store_true",
        help="required with any redaction option set to all",
    )
    v1_import_parser = subparsers.add_parser(
        "import",
        help="validate or apply a typed JSONL LMS import",
    )
    v1_import_parser.add_argument("path", type=Path, help="JSONL file to import")
    apply_group = v1_import_parser.add_mutually_exclusive_group(required=True)
    apply_group.add_argument(
        "--dry-run",
        action="store_true",
        help="validate without writing records",
    )
    apply_group.add_argument(
        "--apply",
        action="store_true",
        help="write records after dry-run validation passes",
    )
    demo_parser = subparsers.add_parser(
        "demo",
        help="run Minimum Demo smoke utilities",
    )
    demo_subparsers = demo_parser.add_subparsers(dest="demo_command")
    demo_subparsers.add_parser(
        "smoke",
        help="exercise the M4 Minimum Demo path with CI-safe fake-provider data",
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
            f"{len(registry.evidence_sources)} evidence sources, "
            f"{len(registry.research_scans)} research scans, "
            f"{len(registry.evidence_reviews)} evidence reviews"
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
    if args.command == "authoring-assist":
        if args.authoring_assist_command == "propose":
            client = LLMClient(
                config=LLMConfig(
                    mode_models={**DEFAULT_MODE_MODELS, "authoring-assist": "fake-authoring-model"},
                    global_daily_cap_micro_usd=1_000_000,
                    default_provider="fake",
                ),
                providers={"fake": FakeProvider()},
                budget=DailyBudgetTracker(mode_caps_micro_usd={}, global_cap_micro_usd=1_000_000),
            )
            draft = ProposalDraft(
                related_node_title=args.related_node_title,
                related_node_knowledge_type=args.related_node_knowledge_type,
                related_node_description=args.related_node_description,
                prompt_body=args.prompt_body,
                prompt_knowledge_type=args.prompt_knowledge_type,
                prompt_intended_cognitive_action=args.prompt_cognitive_action,
                prompt_demand_level=args.prompt_demand_level,
                prompt_expected_answer_form=args.prompt_answer_form,
                edge_type=args.edge_type,
            )
            with session_scope() as session:
                result = propose_authoring_drafts(
                    session,
                    client=client,
                    source_reference_id=args.source_reference,
                    target_node_id=args.target_node,
                    learning_goal_id=args.learning_goal,
                    actor_id=args.actor_id,
                    draft=draft,
                    learner_id=args.learner_id,
                )
                print(
                    "authoring-assist proposal complete: "
                    f"proposal={result.llm_proposal.id} "
                    f"node={result.knowledge_node.id} "
                    f"prompt={result.prompt.id} "
                    f"model={result.llm_proposal.llm_model}"
                )
            return
        authoring_assist_parser.error("authoring-assist requires a subcommand")
    if args.command == "llm":
        if args.llm_command == "replay-eval":
            try:
                entries = load_eval_set(args.path)
            except EvalSetError as exc:
                raise SystemExit(f"replay-eval validation failed: {exc}") from exc
            scenario_counts: dict[str, int] = {}
            for entry in entries:
                scenario_counts[entry.scenario] = scenario_counts.get(entry.scenario, 0) + 1
            print(f"eval set: {args.path}")
            print(f"entries: {len(entries)}")
            for scenario in sorted(scenario_counts):
                print(f"  {scenario}: {scenario_counts[scenario]}")
            if args.dry_run:
                print("dry run: no provider calls issued")
                return
            client = LLMClient(
                config=LLMConfig(
                    mode_models=dict(DEFAULT_MODE_MODELS),
                    global_daily_cap_micro_usd=1_000_000,
                    default_provider="fake",
                ),
                providers={"fake": FakeProvider()},
                budget=DailyBudgetTracker(mode_caps_micro_usd={}, global_cap_micro_usd=1_000_000),
            )
            outcomes = replay_eval_set(client, entries)
            passed = sum(1 for outcome in outcomes if outcome.passed)
            print(f"replayed: {len(outcomes)} entries, {passed} passed")
            for outcome in outcomes:
                status = "PASS" if outcome.passed else "MISS"
                missing = (
                    f" missing={list(outcome.missing_labels)}" if outcome.missing_labels else ""
                )
                print(f"  [{status}] {outcome.entry.entry_id} {outcome.entry.scenario}{missing}")
            return
        llm_parser.error("llm requires a subcommand")
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
        for line in import_summary.to_cli_summary_lines():
            print(line)
        return
    if args.command == "import-graph":
        try:
            with session_scope() as session:
                csv_summary = import_csv_graph(
                    session,
                    args.path,
                    dry_run=args.dry_run,
                    actor_id=args.actor_id,
                )
        except CsvGraphImportError as exc:
            raise SystemExit(f"CSV graph import failed: {exc}") from exc
        print(
            "CSV graph import "
            f"{'dry run' if csv_summary.dry_run else 'complete'}: "
            f"nodes={csv_summary.nodes} "
            f"edges={csv_summary.edges} "
            f"source_references={csv_summary.source_references}"
        )
        return
    if args.command == "export":
        try:
            with session_scope() as session:
                if args.out is None:
                    for line in export_jsonl(
                        session,
                        include_llm_traces=args.include_llm_traces,
                        include_source_content=args.include_source_content,
                        include_pii=args.include_pii,
                        confirm_all=args.yes_i_mean_it,
                    ):
                        print(line)
                else:
                    count = export_to_path(
                        session,
                        args.out,
                        include_llm_traces=args.include_llm_traces,
                        include_source_content=args.include_source_content,
                        include_pii=args.include_pii,
                        confirm_all=args.yes_i_mean_it,
                    )
                    print(f"export complete: records={count} out={args.out}")
        except ExportImportError as exc:
            raise SystemExit(f"export failed: {exc}") from exc
        return
    if args.command == "import":
        try:
            with session_scope() as session:
                summary = import_jsonl(session, args.path, dry_run=args.dry_run)
        except (ExportImportError, SQLAlchemyError) as exc:
            raise SystemExit(f"import failed: {exc}") from exc
        mode = "dry run" if summary.dry_run else "apply"
        counts = " ".join(f"{key}={value}" for key, value in sorted(summary.counts.items()))
        print(f"import {mode} complete: {counts}")
        return
    if args.command == "demo":
        if args.demo_command == "smoke":
            print(render_minimum_demo_smoke(build_minimum_demo_smoke_summary()))
            return
        parser.error("demo requires a subcommand")

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
