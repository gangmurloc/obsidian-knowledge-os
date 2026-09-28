from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import quote

import yaml

from .io_utils import atomic_write_text
from .pdf_extractors import (
    SUPPORTED_EXTRACTORS,
    ExtractedPaper,
    ExtractionWarning,
    PDFExtractionError,
    extract_pdf,
)


LOGGER = logging.getLogger(__name__)
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


class IngestError(RuntimeError):
    """Expected validation or extraction failure."""


class OCRRequiredError(IngestError):
    """The PDF does not contain enough extractable text for v1."""


class OutputCollisionError(IngestError):
    """An output note already represents another source file."""


@dataclass(frozen=True)
class IngestResult:
    status: str
    input_path: Path
    output_path: Path
    pages: int
    extracted_chars: int
    title: str
    extractor: str
    warnings: tuple[ExtractionWarning, ...] = ()
    content_changed: bool | None = None
    existing_chars: int | None = None
    new_chars: int | None = None


def sanitize_filename(value: str, max_length: int = 120) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    normalized = "".join(
        character
        for character in normalized
        if ord(character) >= 32 and character not in '<>:"/\\|?*'
    )
    normalized = re.sub(r"\s+", " ", normalized).strip(" .")
    if not normalized:
        normalized = "untitled"
    if normalized.upper() in WINDOWS_RESERVED_NAMES:
        normalized = f"_{normalized}"
    return normalized[:max_length].rstrip(" .") or "untitled"


def _single_line(value: Any) -> str | None:
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text or None


def normalize_extracted_text_for_markdown(text: str) -> str:
    """Make untrusted PDF plain text safe inside a Markdown content body.

    Some PDF extractors emit a backslash before angle brackets. Remove that
    extraction artifact, then encode angle brackets so Markdown renderers cannot
    interpret source text as raw HTML. This function is intentionally applied
    only to extracted page text, not to generated Markdown or YAML.
    """
    without_extraction_escapes = text.replace(r"\<", "<").replace(r"\>", ">")
    return without_extraction_escapes.replace("<", "&lt;").replace(">", "&gt;")


def _resolve_pdf(pdf_argument: Path, vault_root: Path) -> tuple[Path, Path]:
    root = vault_root.expanduser().resolve()
    pdf_root = (root / "_assets" / "PDF").resolve()
    candidate = pdf_argument.expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate

    try:
        pdf_path = candidate.resolve(strict=True)
    except FileNotFoundError as exc:
        raise IngestError(f"PDF does not exist: {candidate}") from exc

    if not pdf_path.is_file() or pdf_path.suffix.casefold() != ".pdf":
        raise IngestError(f"Input must be a PDF file: {pdf_path}")

    try:
        pdf_path.relative_to(pdf_root)
    except ValueError as exc:
        raise IngestError(f"PDF must be inside {pdf_root}: {pdf_path}") from exc

    return root, pdf_path


def _validate_extracted_paper(paper: ExtractedPaper) -> None:
    minimum_chars = max(80, len(paper.page_texts) * 20)
    if paper.extracted_chars < minimum_chars:
        raise OCRRequiredError(
            f"Only {paper.extracted_chars} text characters were extracted from "
            f"{len(paper.page_texts)} page(s). OCR is required or unavailable."
        )


def _relative_source_path(pdf_path: Path, vault_root: Path) -> str:
    return pdf_path.relative_to(vault_root).as_posix()


FRONTMATTER_PATTERN = re.compile(
    r"\A---[ \t]*\r?\n(?P<yaml>.*?)\r?\n---[ \t]*(?:\r?\n|\Z)",
    re.DOTALL,
)
MANAGED_SOURCE_PROPERTIES = {
    "type",
    "origin",
    "source_type",
    "knowledge_status",
    "title",
    "created",
    "updated",
    "source_file",
    "domain",
    "human_verified",
    "extraction_method",
    "extraction_quality",
    "extraction_warnings",
}


@dataclass(frozen=True)
class ExistingSource:
    metadata: dict[str, Any]
    text: str
    highlights: str
    related: str


def _demote_extracted_headings(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        level = min(6, len(match.group(1)) + 3)
        return f"{'#' * level} "

    return re.sub(r"(?m)^(#{1,6})[ \t]+", replace, text)


def _warning_codes(warnings: tuple[ExtractionWarning, ...]) -> list[str]:
    return sorted({warning.code for warning in warnings})


def _section_body(body: str, heading: str) -> str:
    match = re.search(rf"(?m)^##[ \t]+{re.escape(heading)}[ \t]*$", body)
    if match is None:
        return ""
    next_heading = re.search(r"(?m)^##[ \t]+.+$", body[match.end() :])
    end = match.end() + next_heading.start() if next_heading else len(body)
    return body[match.end() : end].strip()


def _read_existing_source(output_path: Path) -> ExistingSource:
    try:
        text = output_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise IngestError(f"Cannot inspect existing output note: {exc}") from exc
    match = FRONTMATTER_PATTERN.match(text)
    if match is None:
        raise OutputCollisionError(f"Existing output has no valid frontmatter: {output_path}")
    try:
        metadata = yaml.safe_load(match.group("yaml"))
    except yaml.YAMLError as exc:
        raise OutputCollisionError(f"Existing output has malformed frontmatter: {exc}") from exc
    if not isinstance(metadata, dict):
        raise OutputCollisionError(f"Existing output frontmatter is not a mapping: {output_path}")
    if "domain" in metadata and not isinstance(metadata["domain"], list):
        raise OutputCollisionError(f"Existing output domain must be a list: {output_path}")
    if "human_verified" in metadata and not isinstance(metadata["human_verified"], bool):
        raise OutputCollisionError(
            f"Existing output human_verified must be a boolean: {output_path}"
        )
    body = text[match.end() :]
    return ExistingSource(
        metadata=dict(metadata),
        text=text,
        highlights=_section_body(body, "My Highlights"),
        related=_section_body(body, "Related"),
    )


def _render_markdown(
    *,
    title: str,
    source_path: str,
    paper: ExtractedPaper,
    created: str,
    updated: str,
    existing: ExistingSource | None = None,
) -> str:
    content_parts: list[str] = []
    for page_number, text in enumerate(paper.page_texts, start=1):
        extracted = _demote_extracted_headings(text) if paper.extractor == "pymupdf4llm" else text
        normalized_text = normalize_extracted_text_for_markdown(extracted)
        content_parts.append(
            f"### Page {page_number}\n\n"
            f"{normalized_text or '_No extractable text on this page._'}"
        )

    metadata: dict[str, Any] = {
        "type": "source",
        "origin": "external",
        "source_type": "pdf",
        "knowledge_status": "raw",
        "title": title,
        "created": created,
        "updated": updated,
        "source_file": source_path,
        "domain": [],
        "human_verified": False,
        "extraction_method": paper.extractor,
        "extraction_quality": "review" if paper.warnings else "good",
        "extraction_warnings": _warning_codes(paper.warnings),
    }
    highlights = ""
    related = ""
    if existing is not None:
        for key, value in existing.metadata.items():
            if key not in MANAGED_SOURCE_PROPERTIES:
                metadata[key] = value
        metadata["title"] = str(existing.metadata.get("title") or title)
        metadata["domain"] = existing.metadata.get("domain", [])
        metadata["human_verified"] = existing.metadata.get("human_verified", False)
        highlights = existing.highlights
        related = existing.related

    frontmatter = yaml.safe_dump(
        metadata,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
        width=1000,
    ).strip()
    source_link = "../../../" + quote(source_path, safe="/()-_.~")
    warning_lines = [
        f"- `{warning.code}` (PDF p.{warning.page}): {warning.message}"
        if warning.page is not None
        else f"- `{warning.code}`: {warning.message}"
        for warning in paper.warnings
    ]
    extraction_notes = "\n".join(warning_lines) if warning_lines else "- Warnings: none"
    content = "\n\n".join(content_parts)
    note_title = str(metadata["title"])
    return (
        f"---\n{frontmatter}\n---\n\n"
        f"# {note_title}\n\n"
        "## Source\n\n"
        f"- Original PDF: [{Path(source_path).name}](<{source_link}>)\n"
        f"- Pages: {len(paper.page_texts)}\n\n"
        "## Extraction\n\n"
        f"- Method: `{paper.extractor}`\n"
        f"- Quality: `{metadata['extraction_quality']}`\n"
        f"{extraction_notes}\n\n"
        "## Content\n\n"
        f"{content}\n\n"
        "## My Highlights\n\n"
        f"{highlights}\n\n"
        "## Related\n\n"
        f"{related}\n"
    )


def _source_matches(existing: ExistingSource, source_path: str) -> bool:
    return existing.metadata.get("source_file") == source_path


def _atomic_write(output_path: Path, content: str, *, overwrite: bool) -> None:
    try:
        atomic_write_text(output_path, content, overwrite=overwrite)
    except FileExistsError as exc:
        raise OutputCollisionError(f"Output appeared during ingest: {output_path}") from exc


def ingest_paper(
    *,
    pdf_argument: Path,
    vault_root: Path,
    dry_run: bool = True,
    replace: bool = False,
    extractor: str = "pymupdf4llm",
    today: date | None = None,
) -> IngestResult:
    if extractor not in SUPPORTED_EXTRACTORS:
        raise IngestError(
            f"Unsupported extractor {extractor!r}; choose one of {SUPPORTED_EXTRACTORS}."
        )
    if dry_run and replace:
        raise ValueError("replace cannot be combined with dry_run")

    root, pdf_path = _resolve_pdf(pdf_argument, vault_root)
    source_path = _relative_source_path(pdf_path, root)
    output_name = f"{sanitize_filename(pdf_path.stem)}.md"
    output_path = root / "30_Resources" / "Sources" / "Papers" / output_name
    existing = _read_existing_source(output_path) if output_path.exists() else None
    if existing is not None and not _source_matches(existing, source_path):
        raise OutputCollisionError(
            f"Output name collision: {output_path} represents another source. "
            "Rename the PDF explicitly; existing notes are never overwritten."
        )
    if replace and existing is None:
        raise IngestError("--replace requires an existing Source note; use --write to create it.")
    if existing is not None and not dry_run and not replace:
        LOGGER.info("Output already exists for this source; leaving it unchanged.")
        return IngestResult(
            status="exists",
            input_path=pdf_path,
            output_path=output_path,
            pages=0,
            extracted_chars=0,
            title=str(existing.metadata.get("title") or pdf_path.stem),
            extractor=extractor,
        )

    try:
        paper = extract_pdf(pdf_path, extractor=extractor)
    except PDFExtractionError as exc:
        raise IngestError(str(exc)) from exc
    _validate_extracted_paper(paper)
    today_string = (today or date.today()).isoformat()
    title = paper.title or _single_line(pdf_path.stem) or "Untitled Paper"
    created = today_string
    comparison_updated = today_string
    if existing is not None:
        created = str(existing.metadata.get("created") or today_string)
        comparison_updated = str(existing.metadata.get("updated") or created)
    comparison_rendered = _render_markdown(
        title=title,
        source_path=source_path,
        paper=paper,
        created=created,
        updated=comparison_updated,
        existing=existing,
    )
    changed = existing is None or comparison_rendered != existing.text

    if dry_run:
        status = "dry-run-change" if existing is not None and changed else "dry-run"
        if existing is not None and not changed:
            status = "dry-run-unchanged"
        LOGGER.info("Dry run complete; no Markdown was written.")
        rendered = comparison_rendered
    elif replace:
        if not changed:
            status = "unchanged"
            rendered = comparison_rendered
        else:
            rendered = _render_markdown(
                title=title,
                source_path=source_path,
                paper=paper,
                created=created,
                updated=today_string,
                existing=existing,
            )
            _atomic_write(output_path, rendered, overwrite=True)
            status = "replaced"
    else:
        rendered = comparison_rendered
        _atomic_write(output_path, rendered, overwrite=False)
        status = "created"

    return IngestResult(
        status=status,
        input_path=pdf_path,
        output_path=output_path,
        pages=len(paper.page_texts),
        extracted_chars=paper.extracted_chars,
        title=str(existing.metadata.get("title") or title) if existing else title,
        extractor=paper.extractor,
        warnings=paper.warnings,
        content_changed=changed if existing is not None else None,
        existing_chars=len(existing.text) if existing is not None else None,
        new_chars=len(rendered),
    )
