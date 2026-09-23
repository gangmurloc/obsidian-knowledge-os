from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Sequence

from .llm import (
    GenerateRequest,
    LLMError,
    ProviderRequestError,
    create_provider,
    load_llm_config,
)
from .llm.config import resolve_config_path
from .paper_ingest import IngestError, OCRRequiredError, ingest_paper


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
                dry_run=not args.write,
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
    except Exception:
        logging.exception("Unexpected automation failure")
        return 2

    labels = {
        "created": "CREATED",
        "exists": "UNCHANGED",
        "dry-run": "DRY RUN",
    }
    print(
        f"{labels[result.status]}: {result.output_path} "
        f"(pages={result.pages}, extracted_chars={result.extracted_chars})"
    )
    return 0
