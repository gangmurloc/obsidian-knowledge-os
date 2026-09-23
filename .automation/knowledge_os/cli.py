from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Sequence

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
    return parser


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
        else:  # pragma: no cover - argparse enforces the available commands.
            parser.error(f"Unknown command: {args.command}")
    except OCRRequiredError as exc:
        logging.error("OCR required: %s", exc)
        return 3
    except IngestError as exc:
        logging.error("Paper ingest failed: %s", exc)
        return 2
    except Exception:
        logging.exception("Unexpected paper ingest failure")
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
