from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Sequence

from .ai_wiki import AIWikiError, ScanScope, process_ai_wiki
from .llm import (
    GenerateRequest,
    LLMError,
    ProviderRequestError,
    create_provider,
    load_llm_config,
)
from .llm.config import resolve_config_path
from .paper_ingest import IngestError, OCRRequiredError, ingest_paper
from .pdf_extractors import SUPPORTED_EXTRACTORS


def default_vault_root() -> Path:
    return Path(__file__).resolve().parents[2]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gangil-knowledge-os",
        description="Local-only automation for the Gangil Obsidian Vault.",
    )
    parser.add_argument(
        "--vault",
        type=Path,
        default=default_vault_root(),
        help="Vault root. Defaults to the parent of .automation.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show informational logs.",
    )

    commands = parser.add_subparsers(dest="command", required=True)
    ingest = commands.add_parser(
        "ingest-paper",
        help="Extract a text-layer PDF into an Obsidian Markdown source note.",
    )
    ingest.add_argument("pdf", type=Path, help="PDF under _assets/PDF/.")
    write_mode = ingest.add_mutually_exclusive_group()
    write_mode.add_argument(
        "--write",
        action="store_true",
        help="Create the Markdown note. Without this flag, the command is a dry run.",
    )
    write_mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Explicitly extract and validate without writing Markdown (the default).",
    )
    write_mode.add_argument(
        "--replace",
        action="store_true",
        help=(
            "Atomically replace an existing note for the same PDF after re-extraction; "
            "preserves user-owned sections and custom properties."
        ),
    )
    ingest.add_argument(
        "--extractor",
        choices=SUPPORTED_EXTRACTORS,
        default="pymupdf4llm",
        help="Local extraction backend (default: pymupdf4llm; pypdf is legacy).",
    )

    llm_status = commands.add_parser(
        "llm-status",
        help="Check local LLM configuration, connectivity, and installed models.",
    )
    llm_status.add_argument(
        "--config",
        type=Path,
        help="Config path relative to the Vault, or an absolute path.",
    )

    llm_test = commands.add_parser(
        "llm-test",
        help="Explicitly send one small generation request to the configured local model.",
    )
    llm_test.add_argument(
        "--config",
        type=Path,
        help="Config path relative to the Vault, or an absolute path.",
    )
    llm_test.add_argument(
        "--model",
        help="One-time installed model override; does not modify config.",
    )
    llm_test.add_argument(
        "--prompt",
        default="Reply with exactly: LOCAL_LLM_OK",
        help="Prompt for the explicit connectivity test.",
    )

    ai_wiki = commands.add_parser(
        "ai-wiki",
        help="Plan or write AI-maintained concept notes from normalized Sources.",
    )
    ai_wiki_commands = ai_wiki.add_subparsers(dest="ai_wiki_command", required=True)
    scan = ai_wiki_commands.add_parser(
        "scan",
        help="Extract concepts from new or changed Source Markdown.",
    )
    scope = scan.add_mutually_exclusive_group(required=True)
    scope.add_argument("--source", help="One Markdown filename, optionally under Papers/ or Web/.")
    scope.add_argument("--papers", action="store_true", help="Scan paper Sources.")
    scope.add_argument("--web", action="store_true", help="Scan web Sources.")
    scope.add_argument("--all", action="store_true", help="Scan all Source folders.")
    scope.add_argument(
        "--changed",
        action="store_true",
        help="Scan new and changed Sources across Papers and Web.",
    )
    scan.add_argument(
        "--write",
        action="store_true",
        help="Atomically apply the plan to AI-Wiki and processing state.",
    )
    scan.add_argument(
        "--config",
        type=Path,
        help="Config path relative to the Vault, or an absolute path.",
    )
    return parser


def _load_local_provider(vault: Path, configured_path: Path | None):
    config_path = resolve_config_path(vault, configured_path)
    config = load_llm_config(config_path)
    return config, create_provider(config), config_path


def _run_llm_status(vault: Path, configured_path: Path | None) -> int:
    config, provider, config_path = _load_local_provider(vault, configured_path)
    health = provider.health_check()
    models = []
    model_error = None
    if health.reachable:
        try:
            models = provider.list_models()
        except LLMError as exc:
            model_error = str(exc)

    print(f"config: {config_path}")
    print(f"provider: {provider.name}")
    print(f"endpoint: {provider.endpoint}")
    print(f"server_reachable: {str(health.reachable).lower()}")
    print(f"server_version: {health.version or '(unavailable)'}")
    print(f"configured_model: {config.model or '(not set)'}")
    if models:
        print("installed_models:")
        for model in models:
            print(f"  - {model.name}")
    else:
        print("installed_models: (none or unavailable)")
    if health.error:
        print(f"error: {health.error}")
    if model_error:
        print(f"model_error: {model_error}")
    return 0 if health.reachable and model_error is None else 1


def _run_llm_test(
    vault: Path,
    configured_path: Path | None,
    *,
    model: str | None,
    prompt: str,
) -> int:
    _config, provider, _config_path = _load_local_provider(vault, configured_path)
    health = provider.health_check()
    if not health.reachable:
        raise ProviderRequestError(
            health.error or f"Local {provider.name} server is not reachable."
        )
    response = provider.generate(GenerateRequest(prompt=prompt, model=model))
    print(f"provider: {response.provider}")
    print(f"model: {response.model}")
    print(f"done: {str(response.done).lower()}")
    print("response:")
    print(response.text)
    return 0


def _scan_scope(args: argparse.Namespace) -> ScanScope:
    if args.source:
        return ScanScope("source", args.source)
    if args.papers:
        return ScanScope("papers")
    if args.web:
        return ScanScope("web")
    if args.all:
        return ScanScope("all")
    return ScanScope("changed")


def _print_ai_wiki_plan(plan, vault_root: Path, *, write: bool) -> None:
    print(f"mode: {'write' if write else 'dry-run'}")
    print("statistics:")
    print(f"  source_characters: {plan.stats.source_characters}")
    print(f"  processing_characters: {plan.stats.processing_characters}")
    print(f"  chunk_count: {plan.stats.chunk_count}")
    print(f"  included_blocks: {plan.stats.included_blocks}")
    print(f"  average_chunk_size: {plan.stats.average_chunk_size:.1f}")
    print(f"  maximum_chunk_size: {plan.stats.maximum_chunk_size}")
    print(f"  llm_calls: {plan.stats.llm_calls}")
    print(f"  json_repairs: {plan.stats.json_repairs}")
    print(f"  timeout_failures: {plan.stats.timeout_failures}")
    print(f"  curator_calls: {plan.stats.curator_calls}")
    print("processed_sources:")
    for source in plan.processed_sources:
        print(f"  - {source}")
    if not plan.processed_sources:
        print("  (none)")

    for label, values in (
        ("included_sections", plan.included_sections),
        ("excluded_sections", plan.excluded_sections),
        ("excluded_tables", plan.excluded_tables),
        ("excluded_figure_text", plan.excluded_figure_text),
        ("formula_warnings", plan.formula_warnings),
        ("candidate_concepts", plan.candidate_concepts),
        ("selected_concepts", plan.selected_concepts),
        ("dropped_concepts", plan.dropped_concepts),
        ("duplicate_risk_groups", plan.duplicate_risk_groups),
        ("curator_trigger_reason", plan.curator_trigger_reason),
        ("selected_representatives", plan.selected_representatives),
        ("dropped_aliases", plan.dropped_aliases),
    ):
        print(f"{label}:")
        for value in values:
            print(f"  - {value}")
        if not values:
            print("  (none)")

    categories = (
        ("new_concepts", "create"),
        ("existing_concepts_to_update", "update"),
        ("unchanged_concepts", "unchanged"),
    )
    for label, action in categories:
        print(f"{label}:")
        matches = [change for change in plan.changes if change.action == action]
        for change in matches:
            relative = change.path.resolve().relative_to(vault_root.resolve()).as_posix()
            relation = f" ({change.relation})" if change.relation else ""
            print(f"  - {change.title}{relation}: {relative}")
        if not matches:
            print("  (none)")

    print("relation_suggestions:")
    for suggestion in plan.relation_suggestions:
        print(
            f"  - {suggestion.subject} {suggestion.relation} {suggestion.object} "
            f"({suggestion.reason})"
        )
    if not plan.relation_suggestions:
        print("  (none)")

    for label, values in (
        ("skipped", plan.skipped),
        ("removed_sources", plan.removed_sources),
        ("warnings", plan.warnings),
        ("failures", plan.failures),
    ):
        print(f"{label}:")
        for value in values:
            print(f"  - {value}")
        if not values:
            print("  (none)")


def _run_ai_wiki_scan(args: argparse.Namespace) -> int:
    config, provider, _config_path = _load_local_provider(args.vault, args.config)
    if not config.model:
        raise AIWikiError("Local LLM model is not configured.")
    plan = process_ai_wiki(
        vault_root=args.vault,
        provider=provider,
        model_name=config.model,
        scope=_scan_scope(args),
        write=args.write,
    )
    _print_ai_wiki_plan(plan, args.vault, write=args.write)
    return 5 if plan.failures else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s: %(message)s",
    )

    try:
        if args.command == "ingest-paper":
            result = ingest_paper(
                pdf_argument=args.pdf,
                vault_root=args.vault,
                dry_run=not (args.write or args.replace),
                replace=args.replace,
                extractor=args.extractor,
            )
        elif args.command == "llm-status":
            return _run_llm_status(args.vault, args.config)
        elif args.command == "llm-test":
            return _run_llm_test(
                args.vault,
                args.config,
                model=args.model,
                prompt=args.prompt,
            )
        elif args.command == "ai-wiki":
            return _run_ai_wiki_scan(args)
        else:  # pragma: no cover - argparse enforces the available commands.
            parser.error(f"Unknown command: {args.command}")
    except OCRRequiredError as exc:
        logging.error("OCR required: %s", exc)
        return 3
    except IngestError as exc:
        logging.error("Paper ingest failed: %s", exc)
        return 2
    except LLMError as exc:
        logging.error("Local LLM operation failed: %s", exc)
        return 4
    except AIWikiError as exc:
        logging.error("AI-Wiki processing failed: %s", exc)
        return 5
    except Exception:
        logging.exception("Unexpected automation failure")
        return 2

    labels = {
        "created": "CREATED",
        "exists": "UNCHANGED",
        "dry-run": "DRY RUN",
        "dry-run-change": "DRY RUN (CHANGES FOUND)",
        "dry-run-unchanged": "DRY RUN (UNCHANGED)",
        "replaced": "REPLACED",
        "unchanged": "UNCHANGED",
    }
    print(
        f"{labels[result.status]}: {result.output_path} "
        f"(extractor={result.extractor}, pages={result.pages}, "
        f"extracted_chars={result.extracted_chars}, warnings={len(result.warnings)})"
    )
    if result.content_changed is not None:
        print(f"content_changed: {str(result.content_changed).lower()}")
        print(f"existing_chars: {result.existing_chars}")
        print(f"candidate_chars: {result.new_chars}")
    for warning in result.warnings:
        page = f" page={warning.page}" if warning.page is not None else ""
        print(f"warning: {warning.code}{page}: {warning.message}")
    return 0
