from __future__ import annotations

import importlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SUPPORTED_EXTRACTORS = ("pymupdf4llm", "pypdf")


class PDFExtractionError(RuntimeError):
    """A local PDF extractor could not produce a safe page sequence."""


@dataclass(frozen=True)
class ExtractionWarning:
    code: str
    page: int | None
    message: str


@dataclass(frozen=True)
class ExtractedPaper:
    title: str | None
    page_texts: tuple[str, ...]
    extracted_chars: int
    extractor: str
    warnings: tuple[ExtractionWarning, ...] = ()


def _single_line(value: Any) -> str | None:
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text or None


def _clean_page_text(value: str) -> str:
    text = value.replace("\x00", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.rstrip() for line in text.split("\n")).strip()


def _extracted_character_count(page_texts: list[str]) -> int:
    return sum(len(re.sub(r"\s+", "", text)) for text in page_texts)


def _table_row_column_count(line: str) -> int:
    return len([cell for cell in line.strip().strip("|").split("|")])


def _is_table_separator(line: str) -> bool:
    cells = line.strip().strip("|").split("|")
    return bool(cells) and all(re.fullmatch(r"\s*:?-{3,}:?\s*", cell) for cell in cells)


def _quality_warnings(page_texts: list[str]) -> list[ExtractionWarning]:
    warnings: list[ExtractionWarning] = []
    for page_number, text in enumerate(page_texts, start=1):
        lines = [line for line in text.splitlines() if line.strip()]
        joined_words = len(
            re.findall(
                r"(?:[a-z][A-Z][A-Z0-9-]{2,}|[A-Z][A-Z0-9-]{2,}[a-z]{3,})",
                text,
            )
        )
        if joined_words >= 3:
            warnings.append(
                ExtractionWarning(
                    "word_joining",
                    page_number,
                    f"detected {joined_words} likely joined word boundaries",
                )
            )

        table_lines = [line for line in lines if "|" in line]
        if table_lines:
            counts = {_table_row_column_count(line) for line in table_lines}
            if len(counts) > 1 or not any(_is_table_separator(line) for line in table_lines):
                warnings.append(
                    ExtractionWarning(
                        "table_layout",
                        page_number,
                        "Markdown table rows have inconsistent structure",
                    )
                )

        dense_rows = 0
        for line in lines:
            numeric_tokens = len(re.findall(r"(?<!\w)[+-]?\d+(?:[.,]\d+)*(?!\w)", line))
            if len(line) >= 120 and numeric_tokens >= 6 and "|" not in line:
                dense_rows += 1
        if dense_rows >= 2:
            warnings.append(
                ExtractionWarning(
                    "table_layout",
                    page_number,
                    f"detected {dense_rows} dense unstructured numeric rows",
                )
            )

        suspicious_formulas = sum(
            1
            for line in lines
            if re.search(r"\(\d+\)\s*$", line)
            and "$$" not in line
            and len(
                re.findall(
                    r"[=+*/^_<>]|\\(?:frac|sum|prod|sqrt|alpha|beta)",
                    line,
                )
            )
            >= 2
        )
        if suspicious_formulas:
            warnings.append(
                ExtractionWarning(
                    "formula_layout",
                    page_number,
                    f"detected {suspicious_formulas} flattened formula lines",
                )
            )

        interleaved_lines = sum(
            1
            for line in lines
            if len(line) >= 100
            and (
                re.search(r"\}[A-Z]", line)
                or len(re.findall(r"\b(?:Table|Figure|Prompt Template)\b", line)) >= 2
            )
        )
        if interleaved_lines:
            warnings.append(
                ExtractionWarning(
                    "reading_order",
                    page_number,
                    f"detected {interleaved_lines} potentially interleaved lines",
                )
            )

    unique: dict[tuple[str, int | None], ExtractionWarning] = {}
    for warning in warnings:
        unique.setdefault((warning.code, warning.page), warning)
    return list(unique.values())


def _load_pymupdf4llm():
    try:
        return importlib.import_module("pymupdf4llm")
    except ImportError as exc:
        raise PDFExtractionError(
            "Missing dependency 'pymupdf4llm'. Install .automation/requirements.txt first."
        ) from exc


def _extract_pymupdf4llm(pdf_path: Path) -> ExtractedPaper:
    module = _load_pymupdf4llm()
    try:
        chunks = module.to_markdown(
            str(pdf_path),
            page_chunks=True,
            header=False,
            footer=False,
            write_images=False,
            embed_images=False,
            show_progress=False,
            use_ocr=True,
        )
    except Exception as exc:
        raise PDFExtractionError(f"PyMuPDF4LLM extraction failed: {exc}") from exc

    if not isinstance(chunks, list) or not chunks:
        raise PDFExtractionError("PyMuPDF4LLM returned no page chunks.")

    ordered: list[tuple[int, str, dict[str, Any]]] = []
    for index, chunk in enumerate(chunks, start=1):
        if not isinstance(chunk, dict):
            raise PDFExtractionError(f"PyMuPDF4LLM page chunk {index} is not an object.")
        metadata = chunk.get("metadata")
        text = chunk.get("text")
        if not isinstance(metadata, dict) or not isinstance(text, str):
            raise PDFExtractionError(
                f"PyMuPDF4LLM page chunk {index} is missing metadata or text."
            )
        page_number = metadata.get("page_number", metadata.get("page", index))
        if isinstance(page_number, bool) or not isinstance(page_number, int):
            raise PDFExtractionError(f"PyMuPDF4LLM page chunk {index} has no page number.")
        ordered.append((page_number, _clean_page_text(text), metadata))

    ordered.sort(key=lambda value: value[0])
    page_numbers = [value[0] for value in ordered]
    if page_numbers != list(range(1, len(ordered) + 1)):
        raise PDFExtractionError(
            f"PyMuPDF4LLM returned a non-contiguous page sequence: {page_numbers}"
        )

    page_texts = [value[1] for value in ordered]
    title = _single_line(ordered[0][2].get("title"))
    return ExtractedPaper(
        title=title,
        page_texts=tuple(page_texts),
        extracted_chars=_extracted_character_count(page_texts),
        extractor="pymupdf4llm",
        warnings=tuple(_quality_warnings(page_texts)),
    )


class _WarningCapture(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


def _open_pypdf_reader(pdf_path: Path):
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise PDFExtractionError(
            "Missing dependency 'pypdf'. Install .automation/requirements.txt first."
        ) from exc
    try:
        return PdfReader(str(pdf_path))
    except Exception as exc:
        raise PDFExtractionError(f"Cannot open PDF with pypdf: {exc}") from exc


def _extract_pypdf_reader(reader: Any) -> ExtractedPaper:
    if getattr(reader, "is_encrypted", False):
        try:
            decrypt_result = reader.decrypt("")
        except Exception as exc:
            raise PDFExtractionError(f"Encrypted PDF cannot be opened: {exc}") from exc
        if not decrypt_result:
            raise PDFExtractionError("Encrypted PDF requires a password.")

    metadata = getattr(reader, "metadata", None)
    title = _single_line(getattr(metadata, "title", None)) if metadata else None
    try:
        pages = list(reader.pages)
    except Exception as exc:
        raise PDFExtractionError(f"Cannot read PDF pages: {exc}") from exc
    if not pages:
        raise PDFExtractionError("PDF contains no pages.")

    page_texts: list[str] = []
    captured: list[ExtractionWarning] = []
    logger = logging.getLogger("pypdf")
    handler = _WarningCapture()
    logger.addHandler(handler)
    try:
        for page_number, page in enumerate(pages, start=1):
            before = len(handler.messages)
            try:
                try:
                    extracted = page.extract_text(extraction_mode="layout")
                except TypeError:
                    extracted = page.extract_text()
            except Exception as exc:
                raise PDFExtractionError(
                    f"pypdf text extraction failed on page {page_number}: {exc}"
                ) from exc
            page_texts.append(_clean_page_text(extracted or ""))
            for message in handler.messages[before:]:
                code = "rotated_text" if "Rotated text" in message else "extractor_warning"
                captured.append(ExtractionWarning(code, page_number, message.strip()))
    finally:
        logger.removeHandler(handler)

    captured.extend(_quality_warnings(page_texts))
    unique: dict[tuple[str, int | None], ExtractionWarning] = {}
    for warning in captured:
        unique.setdefault((warning.code, warning.page), warning)
    return ExtractedPaper(
        title=title,
        page_texts=tuple(page_texts),
        extracted_chars=_extracted_character_count(page_texts),
        extractor="pypdf",
        warnings=tuple(unique.values()),
    )


def extract_pdf(pdf_path: Path, *, extractor: str) -> ExtractedPaper:
    if extractor not in SUPPORTED_EXTRACTORS:
        raise PDFExtractionError(
            f"Unsupported PDF extractor {extractor!r}; choose one of {SUPPORTED_EXTRACTORS}."
        )
    if extractor == "pymupdf4llm":
        return _extract_pymupdf4llm(pdf_path)
    return _extract_pypdf_reader(_open_pypdf_reader(pdf_path))
