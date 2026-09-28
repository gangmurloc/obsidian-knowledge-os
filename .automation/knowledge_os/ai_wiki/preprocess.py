from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass


AI_PROCESSING_VIEW_VERSION = 5
PAGE_HEADING_PATTERN = re.compile(r"^###[ \t]+Page[ \t]+(?P<page>\d+)[ \t]*$", re.I)
SECTION_HEADING_PATTERN = re.compile(
    r"^(?P<marks>#{1,6})[ \t]+(?P<title>.+?)[ \t]*$"
)
EXCLUDED_SECTION_TITLES = {
    "references",
    "bibliography",
    "contents",
    "table of contents",
    "neurips paper checklist",
    "paper checklist",
}
TOC_ENTRY_PATTERN = re.compile(r"^.{2,100}(?:\.{2,}|[ \t]{2,})[ \t]*\d+[ \t]*$")
FIGURE_CAPTION_PATTERN = re.compile(
    r"^(?:figure|fig[.])[ \t]*[A-Z]?\d+(?:[.:]|[ \t]+[-])[ \t]*\S+",
    re.I,
)
MARKDOWN_IMAGE_PATTERN = re.compile(r"^!\[[^]]*]\([^)]+\)[ \t]*$")
PICTURE_TEXT_PATTERN = re.compile(
    r"^(?:\[|<)?(?:picture|image|figure)[-_ ]?(?:text|ocr)?(?:[ \t]+\d+(?:[-.]\d+)*)?"
    r"(?:\]|>|:|[ \t]*$)",
    re.I,
)
FORMULA_INTRO_PATTERN = re.compile(
    r"\b(?:equation|formula|objective|loss|probability|attention|score|function)\b"
    r".*\b(?:defined|computed|given|written|expressed)\b.*(?:\bas\b|\bby\b)[ \t:]*$",
    re.I,
)
OMISSION_MARKER_PATTERN = re.compile(r"^> \[.+ omitted from AI extraction:")


@dataclass(frozen=True)
class AIProcessingView:
    content: str
    included_sections: tuple[str, ...] = ()
    excluded_sections: tuple[str, ...] = ()
    included_blocks: int = 0
    excluded_tables: tuple[str, ...] = ()
    excluded_figure_text: tuple[str, ...] = ()
    formula_warnings: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


def _heading_title(line: str) -> str | None:
    match = SECTION_HEADING_PATTERN.fullmatch(line.strip())
    return match.group("title").strip() if match else None


def _heading_info(line: str) -> tuple[int, str] | None:
    stripped = line.strip()
    if PAGE_HEADING_PATTERN.fullmatch(stripped):
        return None
    match = SECTION_HEADING_PATTERN.fullmatch(stripped)
    if match is None:
        return None
    return len(match.group("marks")), match.group("title").strip()


def canonicalize_heading_text(value: str) -> str:
    text = unicodedata.normalize("NFKC", html.unescape(value))
    text = re.sub(r"<[^>]{1,200}>", " ", text)
    text = re.sub(r"!\[([^]]*)]\([^)]+\)", r"\1", text)
    text = re.sub(r"\[([^]]+)]\([^)]+\)", r"\1", text)
    text = re.sub(r"`+([^`]*)`+", r"\1", text)
    text = re.sub(r"[*_~]+", "", text)
    text = re.sub(r"^\s*(?:section\s+)?\d+(?:\.\d+)*(?:[.)])?\s+", "", text, flags=re.I)
    text = re.sub(r"[^\w\s-]", " ", text, flags=re.UNICODE)
    text = re.sub(r"[-\s]+", " ", text).strip().casefold()
    return text


def _is_table_separator(line: str) -> bool:
    cells = line.strip().strip("|").split("|")
    return bool(cells) and all(re.fullmatch(r"[ \t]*:?-{3,}:?[ \t]*", cell) for cell in cells)


def _table_column_count(line: str) -> int:
    return len(line.strip().strip("|").split("|"))


def _valid_gfm_table(lines: list[str]) -> bool:
    if len(lines) < 2 or not all("|" in line for line in lines):
        return False
    counts = {_table_column_count(line) for line in lines}
    return len(counts) == 1 and _is_table_separator(lines[1])


def _operator_count(line: str) -> int:
    return len(
        re.findall(
            r"[=+*/^_<>]|\\(?:frac|sum|prod|sqrt|alpha|beta|gamma|theta)",
            line,
        )
    )


def _looks_like_formula(line: str) -> bool:
    stripped = line.strip()
    return bool(
        "$$" in stripped
        or re.search(r"\\\[|\\\]|\\\(|\\\)", stripped)
        or (_operator_count(stripped) >= 2 and len(stripped) >= 10)
    )


def _looks_like_flattened_formula(line: str) -> bool:
    stripped = line.strip()
    return bool(
        re.search(r"\(\d+\)$", stripped)
        and "$$" not in stripped
        and _operator_count(stripped) >= 2
        and len(stripped) >= 20
    )


def _numeric_density(line: str) -> float:
    compact = re.sub(r"\s+", "", line)
    if not compact:
        return 0.0
    return sum(character.isdigit() for character in compact) / len(compact)


def _looks_like_dense_table_row(line: str) -> bool:
    numeric_tokens = re.findall(r"(?<!\w)[+-]?\d+(?:[.,]\d+)*(?!\w)", line)
    return bool(
        "|" not in line
        and len(line) >= 80
        and len(numeric_tokens) >= 6
        and _numeric_density(line) >= 0.18
    )


def _joined_word_count(text: str) -> int:
    return len(
        re.findall(
            r"(?:[a-z]{2,}[A-Z][A-Za-z0-9-]{2,}|[A-Z]{3,}[a-z]{3,})",
            text,
        )
    )


def _is_figure_caption(line: str) -> bool:
    return bool(FIGURE_CAPTION_PATTERN.match(line.strip()))


def _is_picture_text_marker(line: str) -> bool:
    stripped = line.strip()
    return bool(
        MARKDOWN_IMAGE_PATTERN.fullmatch(stripped)
        or PICTURE_TEXT_PATTERN.match(stripped)
        or re.search(r"\b(?:picture|image)[-_ ]text\b", stripped, re.I)
    )


def _looks_like_unmarked_ocr_block(lines: list[str]) -> bool:
    text = "\n".join(lines)
    if _joined_word_count(text) < 4:
        return False
    compact_length = len(re.sub(r"\s+", "", text))
    digits = sum(character.isdigit() for character in text)
    numeric_density = digits / compact_length if compact_length else 0.0
    short_line_ratio = sum(len(line.strip()) <= 60 for line in lines) / max(1, len(lines))
    return numeric_density >= 0.15 or (len(lines) >= 3 and short_line_ratio >= 0.75)


def _split_pages(content: str) -> list[tuple[int | None, list[str]]]:
    pages: list[tuple[int | None, list[str]]] = []
    page: int | None = None
    lines: list[str] = []
    for line in content.splitlines():
        match = PAGE_HEADING_PATTERN.fullmatch(line.strip())
        if match:
            if lines or page is not None:
                pages.append((page, lines))
            page = int(match.group("page"))
            lines = [line]
        else:
            lines.append(line)
    if lines or page is not None:
        pages.append((page, lines))
    return pages


def _is_toc_page(lines: list[str]) -> bool:
    significant = [line.strip() for line in lines if line.strip()]
    if significant and PAGE_HEADING_PATTERN.fullmatch(significant[0]):
        significant = significant[1:]
    if not significant:
        return False
    title = canonicalize_heading_text(_heading_title(significant[0]) or significant[0])
    return bool(
        title in {"contents", "table of contents"}
        and sum(bool(TOC_ENTRY_PATTERN.fullmatch(line)) for line in significant[1:]) >= 3
    )


def _page_label(page: int | None) -> str:
    return f"PDF p.{page}" if page is not None else "the source document"


def _marker(kind: str, page: int | None, detail: str = "layout confidence low") -> str:
    return f"> [{kind} omitted from AI extraction: {detail}. See {_page_label(page)}.]"


def _next_nonempty(lines: list[str], start: int) -> str | None:
    for line in lines[start:]:
        if line.strip():
            return line.strip()
    return None


def _filter_layout_blocks(
    lines: list[str], page: int | None
) -> tuple[list[str], list[str], list[str], list[str], list[str]]:
    result: list[str] = []
    excluded_tables: list[str] = []
    excluded_figures: list[str] = []
    formula_warnings: list[str] = []
    warnings: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        if "|" in line:
            end = index + 1
            while end < len(lines) and "|" in lines[end]:
                end += 1
            table = lines[index:end]
            if _valid_gfm_table(table):
                result.extend(table)
            else:
                result.append(_marker("Table", page))
                excluded_tables.append(f"malformed Markdown table ({_page_label(page)})")
                warnings.append(f"low-confidence table omitted on {_page_label(page)}")
            index = end
            continue

        if _looks_like_dense_table_row(line):
            end = index + 1
            while end < len(lines) and _looks_like_dense_table_row(lines[end]):
                end += 1
            if end - index >= 2:
                result.append(_marker("Table", page, "excessive numeric density"))
                excluded_tables.append(f"numeric-density table ({_page_label(page)})")
                warnings.append(f"numeric-density table omitted on {_page_label(page)}")
                index = end
                continue

        if _is_figure_caption(line):
            result.append(line)
            index += 1
            continue

        if _is_picture_text_marker(line):
            end = index + 1
            if not MARKDOWN_IMAGE_PATTERN.fullmatch(stripped):
                while end < len(lines):
                    candidate = lines[end]
                    if not candidate.strip() or _is_figure_caption(candidate):
                        break
                    if PAGE_HEADING_PATTERN.fullmatch(candidate.strip()) or _heading_title(candidate):
                        break
                    end += 1
            result.append(_marker("Figure text", page, "raw picture/OCR text"))
            excluded_figures.append(f"picture-text block ({_page_label(page)})")
            warnings.append(f"raw figure text omitted on {_page_label(page)}")
            index = end
            continue

        if stripped:
            block_end = index + 1
            while block_end < len(lines) and lines[block_end].strip():
                if "|" in lines[block_end] or _is_figure_caption(lines[block_end]):
                    break
                block_end += 1
            block = lines[index:block_end]
            if _looks_like_unmarked_ocr_block(block):
                result.append(_marker("Figure text", page, "probable joined-word OCR text"))
                excluded_figures.append(f"joined-word OCR block ({_page_label(page)})")
                warnings.append(f"excessive joined-word patterns on {_page_label(page)}")
                index = block_end
                continue

        if _looks_like_flattened_formula(line):
            result.append(_marker("Formula", page))
            formula_warnings.append(f"malformed formula ({_page_label(page)})")
            warnings.append(f"low-confidence formula omitted on {_page_label(page)}")
            index += 1
            continue

        result.append(line)
        if FORMULA_INTRO_PATTERN.search(stripped):
            following = _next_nonempty(lines, index + 1)
            if following is None or (
                not _looks_like_formula(following)
                and (
                    PAGE_HEADING_PATTERN.fullmatch(following)
                    or _heading_title(following)
                    or _is_figure_caption(following)
                )
            ):
                result.append(_marker("Formula", page, "expected formula is empty or missing"))
                formula_warnings.append(f"missing formula after introduction ({_page_label(page)})")
                warnings.append(f"missing formula after introduction on {_page_label(page)}")
        index += 1

    return result, excluded_tables, excluded_figures, formula_warnings, warnings


def _included_block_count(content: str) -> int:
    blocks = [block.strip() for block in re.split(r"\n[ \t]*\n", content) if block.strip()]
    return sum(
        1
        for block in blocks
        if not PAGE_HEADING_PATTERN.fullmatch(block)
        and not OMISSION_MARKER_PATTERN.match(block)
    )


def build_ai_processing_view(content: str) -> AIProcessingView:
    output: list[str] = []
    included_sections: list[str] = []
    excluded_sections: list[str] = []
    excluded_tables: list[str] = []
    excluded_figures: list[str] = []
    formula_warnings: list[str] = []
    warnings: list[str] = []
    excluded_heading_level: int | None = None

    for page, lines in _split_pages(content):
        if _is_toc_page(lines):
            if page is not None:
                output.extend([f"### Page {page}", "", _marker("Table of contents", page)])
            excluded_sections.append(f"table of contents ({_page_label(page)})")
            continue

        filtered_section_lines: list[str] = []
        page_marker = lines[0] if lines and PAGE_HEADING_PATTERN.fullmatch(lines[0].strip()) else None
        page_marker_added = False
        page_has_named_section = False
        for line in lines:
            if page_marker is not None and line == page_marker:
                if excluded_heading_level is None:
                    filtered_section_lines.append(line)
                    page_marker_added = True
                continue
            heading = _heading_info(line)
            title = heading[1] if heading else None
            if heading is not None:
                level, title = heading
                canonical_title = canonicalize_heading_text(title)
                if excluded_heading_level is not None and level <= excluded_heading_level:
                    excluded_heading_level = None
                if excluded_heading_level is not None:
                    continue
                if canonical_title in EXCLUDED_SECTION_TITLES:
                    excluded_heading_level = level
                    excluded_sections.append(
                        f"{canonical_title} ({_page_label(page)})"
                    )
                    continue
                if page_marker is not None and not page_marker_added:
                    filtered_section_lines.extend([page_marker, ""])
                    page_marker_added = True
            if excluded_heading_level is not None:
                continue
            if title:
                included_sections.append(f"{title} ({_page_label(page)})")
                page_has_named_section = True
            filtered_section_lines.append(line)

        filtered, tables, figures, formulas, page_warnings = _filter_layout_blocks(
            filtered_section_lines, page
        )
        if not page_has_named_section and any(
            line.strip() and not PAGE_HEADING_PATTERN.fullmatch(line.strip())
            for line in filtered
        ):
            included_sections.append(f"body ({_page_label(page)})")
        output.extend(filtered)
        excluded_tables.extend(tables)
        excluded_figures.extend(figures)
        formula_warnings.extend(formulas)
        warnings.extend(page_warnings)

    normalized = "\n".join(output).strip()
    return AIProcessingView(
        content=normalized,
        included_sections=tuple(dict.fromkeys(included_sections)),
        excluded_sections=tuple(dict.fromkeys(excluded_sections)),
        included_blocks=_included_block_count(normalized),
        excluded_tables=tuple(dict.fromkeys(excluded_tables)),
        excluded_figure_text=tuple(dict.fromkeys(excluded_figures)),
        formula_warnings=tuple(dict.fromkeys(formula_warnings)),
        warnings=tuple(dict.fromkeys(warnings)),
    )
