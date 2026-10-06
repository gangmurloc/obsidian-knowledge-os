from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Sequence

from .ai_wiki import AIWikiError, ScanScope, process_ai_wiki
from .ai_wiki.plan_file import apply_plan, plan_block_reason, review_path, save_plan
from .ai_wiki.verify import check_note
from .llm import (
    GenerateRequest,
    LLMConfig,
    LLMError,
    ProviderRequestError,
    create_provider,
    load_llm_config,
    request_unload,
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
    scan_mode = scan.add_mutually_exclusive_group()
    scan_mode.add_argument(
        "--write",
        action="store_true",
        help="Atomically apply the plan to AI-Wiki and processing state.",
    )
    scan_mode.add_argument(
        "--save-plan",
        action="store_true",
        help=(
            "Save this dry-run under .automation/state/plans/ so `ai-wiki apply` can "
            "write exactly these notes later without calling the model again."
        ),
    )
    scan.add_argument(
        "--config",
        type=Path,
        help="Config path relative to the Vault, or an absolute path.",
    )
    apply = ai_wiki_commands.add_parser(
        "apply",
        help="Review or write a plan saved by `ai-wiki scan --save-plan`; makes no LLM call.",
    )
    apply.add_argument(
        "--plan",
        type=Path,
        required=True,
        help="Plan file relative to the Vault, or an absolute path.",
    )
    apply.add_argument(
        "--write",
        action="store_true",
        help="Write the plan's notes and processing state. Without this flag it only validates and prints.",
    )
    verify = ai_wiki_commands.add_parser(
        "verify",
        help="Check AI-Wiki notes against their Sources and optionally record a delegated review.",
    )
    verify.add_argument(
        "--note",
        action="append",
        required=True,
        help="AI-Wiki note filename; repeat the flag for several notes.",
    )
    verify.add_argument(
        "--write",
        action="store_true",
        help=(
            "Set human_verified: true and record verified_by: ai. "
            "Without this flag the notes are only checked."
        ),
    )
    verify.add_argument(
        "--reviewer",
        help="Name recorded in the note as the AI reviewer; required with --write.",
    )
    return parser


def _load_local_provider(vault: Path, configured_path: Path | None):
    config_path = resolve_config_path(vault, configured_path)
    config = load_llm_config(config_path)
    return config, create_provider(config), config_path


def _gpu_release_lines(config: LLMConfig) -> list[str]:
    keep_alive = "(not set)" if config.keep_alive is None else str(config.keep_alive)
    return [
        f"keep_alive: {keep_alive}",
        f"unload_after_run: {str(config.unload_after_run).lower()}",
    ]


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
    for line in _gpu_release_lines(config):
        print(line)
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
    config, provider, _config_path = _load_local_provider(vault, configured_path)
    health = provider.health_check()
    if not health.reachable:
        raise ProviderRequestError(
            health.error or f"Local {provider.name} server is not reachable."
        )
    unload_requests = 0
    unload_warning = None
    completed = False
    try:
        response = provider.generate(GenerateRequest(prompt=prompt, model=model))
        completed = True
    finally:
        # The try block starts at the only LLM call, so reaching here means one was made.
        unload_model = (model or config.model or "").strip()
        if config.unload_after_run and unload_model:
            unload_requests += 1
            unload_warning = request_unload(provider, unload_model)
            if unload_warning and not completed:
                logging.warning("%s", unload_warning)
    print(f"provider: {response.provider}")
    print(f"endpoint: {provider.endpoint}")
    print(f"model: {response.model}")
    for line in _gpu_release_lines(config):
        print(line)
    print("llm_calls: 1")
    print(f"unload_requests: {unload_requests}")
    if unload_warning:
        print(f"warning: {unload_warning}")
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


def _print_ai_wiki_plan(
    plan,
    vault_root: Path,
    *,
    write: bool,
    config: LLMConfig | None = None,
    endpoint: str | None = None,
) -> None:
    print(f"mode: {'write' if write else 'dry-run'}")
    if config is not None:
        print("llm:")
        print(f"  endpoint: {endpoint or config.base_url}")
        print(f"  model: {config.model or '(not set)'}")
        for line in _gpu_release_lines(config):
            print(f"  {line}")
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
    print(f"  recovery_calls: {plan.stats.recovery_calls}")
    print(f"  unload_requests: {plan.stats.unload_requests}")
    print("quality_gate:")
    print(f"  status: {plan.quality_gate_status}")
    print("  reasons:")
    for reason in plan.quality_gate_reasons:
        print(f"    - {reason}")
    if not plan.quality_gate_reasons:
        print("    (none)")
    print(f"  write_blocked: {str(plan.write_blocked).lower()}")
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
        ("methodology_subsections", plan.methodology_subsections),
        ("candidate_concepts", plan.candidate_concepts),
        ("selected_concepts", plan.selected_concepts),
        ("dropped_concepts", plan.dropped_concepts),
        ("duplicate_risk_groups", plan.duplicate_risk_groups),
        ("curator_trigger_reason", plan.curator_trigger_reason),
        ("selected_representatives", plan.selected_representatives),
        ("dropped_aliases", plan.dropped_aliases),
        ("method_recovery", plan.method_recovery),
        ("method_coverage", plan.method_coverage),
        ("evidence_locatability", plan.evidence_locatability),
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
    scope = _scan_scope(args)
    plan = process_ai_wiki(
        vault_root=args.vault,
        provider=provider,
        model_name=config.model,
        scope=scope,
        write=args.write,
        unload_after_run=config.unload_after_run,
    )
    _print_ai_wiki_plan(
        plan,
        args.vault,
        write=args.write,
        config=config,
        endpoint=provider.endpoint,
    )
    if args.save_plan:
        reason = plan_block_reason(plan)
        if reason is not None:
            print(f"plan_saved: (not saved because of {reason})")
        else:
            saved = save_plan(
                plan,
                vault_root=args.vault,
                scope=scope,
                provider_name=provider.name,
                model_name=config.model,
            )
            root = args.vault.resolve()
            print(f"plan_saved: {saved.relative_to(root).as_posix()}")
            print(f"plan_review: {review_path(saved).relative_to(root).as_posix()}")
    if plan.failures:
        return 5
    return 6 if plan.quality_gate_status == "failed" else 0


def _run_ai_wiki_apply(args: argparse.Namespace) -> int:
    loaded = apply_plan(vault_root=args.vault, plan_path=args.plan, write=args.write)
    print(f"mode: {'write' if args.write else 'dry-run'}")
    print(f"plan: {loaded.relative_path}")
    print(f"created_at: {loaded.created_at}")
    print(f"model: {loaded.model}")
    print("sources:")
    for source in loaded.sources:
        print(f"  - {source}")
    print("changes:")
    for change in loaded.changes:
        relation = f" ({change.relation})" if change.relation else ""
        print(f"  - {change.action}: {change.title}{relation}: {change.relative_path}")
    if not loaded.changes:
        print("  (none)")
    if args.write:
        print(f"status: applied; wrote {len(loaded.changes)} note(s) and the processing state")
        return 0
    for change in loaded.changes:
        print(f"----- {change.action}: {change.relative_path} -----")
        print(change.content.rstrip("\n"))
    print("-----")
    print("status: valid; nothing was written. Add --write to apply this plan.")
    return 0


def _run_ai_wiki_verify(args: argparse.Namespace) -> int:
    if args.write and not (args.reviewer or "").strip():
        raise AIWikiError("--reviewer is required with --write")
    # Check every note before marking any, so one bad note leaves the others untouched.
    checks = [check_note(vault_root=args.vault, note=note) for note in args.note]
    if args.write:
        checks = [
            check_note(vault_root=args.vault, note=note, reviewer=args.reviewer, write=True)
            for note in args.note
        ]
    print(f"mode: {'write' if args.write else 'dry-run'}")
    for check in checks:
        print(f"note: {check.relative_path}")
        if check.status == "already verified":
            print("  status: already verified; left unchanged")
            continue
        print(f"  title: {check.title}")
        print(f"  sources: {', '.join(check.sources)}")
        print(f"  evidence_located: {check.evidence_located}/{check.evidence_total}")
        missing = ", ".join(str(number) for number in check.evidence_not_found) or "(none)"
        print(f"  evidence_not_found: {missing}")
        if check.status == "marked":
            print(
                "  status: marked human_verified: true "
                f"(verified_by: ai, reviewer: {args.reviewer.strip()})"
            )
        else:
            print("  status: checked; nothing was written")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s: %(message)s",
    )
    # A console code page such as cp949 cannot encode every character found in
    # extracted text; escape those characters instead of failing mid-report.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")

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
            if args.ai_wiki_command == "apply":
                return _run_ai_wiki_apply(args)
            if args.ai_wiki_command == "verify":
                return _run_ai_wiki_verify(args)
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
