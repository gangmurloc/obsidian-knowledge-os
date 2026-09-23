from __future__ import annotations

import json
import logging
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .io_utils import atomic_write_text


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


@dataclass(frozen=True)
class ExtractedPaper:
    title: str | None
    page_texts: tuple[str, ...]
    extracted_chars: int


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


def _yaml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


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


def _open_reader(pdf_path: Path):
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise IngestError(
            "Missing dependency 'pypdf'. Install .automation/requirements.txt first."
        ) from exc

    try:
        return PdfReader(str(pdf_path))
    except Exception as exc:
        raise IngestError(f"Cannot open PDF: {exc}") from exc


def _extract_paper(reader: Any) -> ExtractedPaper:
    if getattr(reader, "is_encrypted", False):
        try:
            decrypt_result = reader.decrypt("")
        except Exception as exc:
            raise IngestError(f"Encrypted PDF cannot be opened: {exc}") from exc
        if not decrypt_result:
            raise IngestError("Encrypted PDF requires a password; no output was written.")

    metadata = getattr(reader, "metadata", None)
    title = _single_line(getattr(metadata, "title", None)) if metadata else None
    page_texts: list[str] = []

    try:
        pages = list(reader.pages)
    except Exception as exc:
        raise IngestError(f"Cannot read PDF pages: {exc}") from exc

    if not pages:
        raise IngestError("PDF contains no pages; no output was written.")

    for page_number, page in enumerate(pages, start=1):
        try:
            try:
                extracted = page.extract_text(extraction_mode="layout")
            except TypeError:
                extracted = page.extract_text()
        except Exception as exc:
            raise IngestError(f"Text extraction failed on page {page_number}: {exc}") from exc

        text = (extracted or "").replace("\x00", "")
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = "\n".join(line.rstrip() for line in text.split("\n")).strip()
        page_texts.append(text)

    extracted_chars = sum(len(re.sub(r"\s+", "", text)) for text in page_texts)
    minimum_chars = max(80, len(page_texts) * 20)
    if extracted_chars < minimum_chars:
        raise OCRRequiredError(
            f"Only {extracted_chars} text characters were extracted from "
            f"{len(page_texts)} page(s). The file is likely image-based."
        )

    return ExtractedPaper(
        title=title,
        page_texts=tuple(page_texts),
        extracted_chars=extracted_chars,
    )


def _relative_source_path(pdf_path: Path, vault_root: Path) -> str:
    return pdf_path.relative_to(vault_root).as_posix()


def _render_markdown(
    *,
    title: str,
    source_path: str,
    page_texts: tuple[str, ...],
    today: str,
) -> str:
    content_parts: list[str] = []
    for page_number, text in enumerate(page_texts, start=1):
        normalized_text = normalize_extracted_text_for_markdown(text)
        content_parts.append(
            f"### Page {page_number}\n\n"
            f"{normalized_text or '_No extractable text on this page._'}"
        )

    source_link = "../../../" + quote(source_path, safe="/()-_.~")
    content = "\n\n".join(content_parts)
    return (
        "---\n"
        "type: source\n"
        "origin: external\n"
        "source_type: pdf\n"
        "knowledge_status: raw\n"
        f"title: {_yaml_string(title)}\n"
        f"created: {today}\n"
        f"updated: {today}\n"
        f"source_file: {_yaml_string(source_path)}\n"
        "domain: []\n"
        "human_verified: false\n"
        "---\n\n"
        f"# {title}\n\n"
        "## Source\n\n"
        f"- Original PDF: [{Path(source_path).name}](<{source_link}>)\n"
        f"- Pages: {len(page_texts)}\n\n"
        "## Content\n\n"
        f"{content}\n\n"
        "## My Highlights\n\n"
        "## Related\n"
    )


def _existing_source_matches(output_path: Path, source_path: str) -> bool:
    try:
        with output_path.open("r", encoding="utf-8") as handle:
            prefix = handle.read(8192)
    except (OSError, UnicodeError) as exc:
        raise IngestError(f"Cannot inspect existing output note: {exc}") from exc
    return f"source_file: {_yaml_string(source_path)}" in prefix


def _atomic_write(output_path: Path, content: str) -> None:
    try:
        atomic_write_text(output_path, content, overwrite=False)
    except FileExistsError as exc:
        raise OutputCollisionError(f"Output appeared during ingest: {output_path}") from exc


def ingest_paper(
    *,
    pdf_argument: Path,
    vault_root: Path,
    dry_run: bool = True,
    today: date | None = None,
) -> IngestResult:
    root, pdf_path = _resolve_pdf(pdf_argument, vault_root)
    source_path = _relative_source_path(pdf_path, root)
    output_name = f"{sanitize_filename(pdf_path.stem)}.md"
    output_path = root / "30_Resources" / "Sources" / "Papers" / output_name

    if output_path.exists():
        if not _existing_source_matches(output_path, source_path):
            raise OutputCollisionError(
                f"Output name collision: {output_path} represents another source. "
                "Rename the PDF explicitly; existing notes are never overwritten."
            )
        LOGGER.info("Output already exists for this source; leaving it unchanged.")
        return IngestResult(
            status="exists",
            input_path=pdf_path,
            output_path=output_path,
            pages=0,
            extracted_chars=0,
            title=pdf_path.stem,
        )

    paper = _extract_paper(_open_reader(pdf_path))
    title = paper.title or _single_line(pdf_path.stem) or "Untitled Paper"
    rendered = _render_markdown(
        title=title,
        source_path=source_path,
        page_texts=paper.page_texts,
        today=(today or date.today()).isoformat(),
    )

    if dry_run:
        LOGGER.info("Dry run complete; no Markdown was written.")
        status = "dry-run"
    else:
        _atomic_write(output_path, rendered)
        LOGGER.info("Created %s", output_path)
        status = "created"

    return IngestResult(
        status=status,
        input_path=pdf_path,
        output_path=output_path,
        pages=len(paper.page_texts),
        extracted_chars=paper.extracted_chars,
        title=title,
    )
