from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml

from .models import SourceChunk, SourceNote, SourceValidationError


FRONTMATTER_PATTERN = re.compile(
    r"\A---[ \t]*\r?\n(?P<yaml>.*?)\r?\n---[ \t]*(?:\r?\n|\Z)",
    re.DOTALL,
)
REQUIRED_SOURCE_PROPERTIES = {
    "type",
    "origin",
    "source_type",
    "knowledge_status",
    "domain",
    "created",
    "updated",
    "human_verified",
}
SUPPORTED_SOURCE_TYPES = {"pdf", "web", "html"}
DEFAULT_MAX_CHUNK_CHARS = 4_000
DEFAULT_CHUNK_OVERLAP_CHARS = 200
BLOCK_SEPARATOR_PATTERN = re.compile(r"\n[ \t]*\n")
SENTENCE_BREAK_PATTERN = re.compile(r"(?<=[.!?。！？])\s+")


def parse_markdown_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    match = FRONTMATTER_PATTERN.match(text)
    if match is None:
        raise SourceValidationError("missing YAML frontmatter")
    try:
        metadata = yaml.safe_load(match.group("yaml"))
    except yaml.YAMLError as exc:
        raise SourceValidationError(f"malformed YAML frontmatter: {exc}") from exc
    if not isinstance(metadata, dict):
        raise SourceValidationError("frontmatter must be a YAML mapping")
    if any(not isinstance(key, str) for key in metadata):
        raise SourceValidationError("frontmatter property names must be strings")
    return dict(metadata), text[match.end() :]


def _source_content(body: str) -> str:
    content_heading = re.search(r"(?m)^##[ \t]+Content[ \t]*$", body)
    if content_heading is None:
        return body.strip()
    start = content_heading.end()
    next_heading = re.search(r"(?m)^##[ \t]+(?!Content[ \t]*$).+$", body[start:])
    end = start + next_heading.start() if next_heading else len(body)
    return body[start:end].strip()


def load_source_note(path: Path, vault_root: Path) -> SourceNote:
    root = vault_root.resolve()
    resolved = path.resolve()
    allowed_roots = [
        (root / "30_Resources" / "Sources" / "Papers").resolve(),
        (root / "30_Resources" / "Sources" / "Web").resolve(),
    ]
    if not any(_is_relative_to(resolved, allowed) for allowed in allowed_roots):
        raise SourceValidationError("source is outside Sources/Papers and Sources/Web")
    try:
        raw = resolved.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise SourceValidationError(f"cannot read UTF-8 source: {exc}") from exc

    metadata, body = parse_markdown_frontmatter(raw)
    missing = sorted(REQUIRED_SOURCE_PROPERTIES - set(metadata))
    if missing:
        raise SourceValidationError(f"missing required properties: {', '.join(missing)}")
    if metadata.get("type") != "source":
        raise SourceValidationError("type must be source")
    if metadata.get("origin") != "external":
        raise SourceValidationError("origin must be external")
    if metadata.get("source_type") not in SUPPORTED_SOURCE_TYPES:
        raise SourceValidationError("source_type must be pdf, web, or html")
    if metadata.get("knowledge_status") != "raw":
        raise SourceValidationError("knowledge_status must be raw for a Source")
    if not isinstance(metadata.get("domain"), list):
        raise SourceValidationError("domain must be a list")
    if not isinstance(metadata.get("human_verified"), bool):
        raise SourceValidationError("human_verified must be a boolean")
    title = metadata.get("title")
    if title is not None and (not isinstance(title, str) or not title.strip()):
        raise SourceValidationError("title must be a non-empty string when present")
    source_url = metadata.get("source_url")
    if source_url is not None:
        if not isinstance(source_url, str) or urlsplit(source_url).scheme not in {"http", "https"}:
            raise SourceValidationError("source_url must be an absolute HTTP(S) URL")
    source_file = metadata.get("source_file")
    if source_file is not None:
        if not isinstance(source_file, str) or not source_file.strip():
            raise SourceValidationError("source_file must be a non-empty string when present")
        if Path(source_file).is_absolute():
            raise SourceValidationError("source_file must be Vault-relative")

    content = _source_content(body)
    if not content:
        raise SourceValidationError("source content is empty")
    relative_path = resolved.relative_to(root).as_posix()
    return SourceNote(
        path=resolved,
        relative_path=relative_path,
        note_name=resolved.stem,
        metadata=metadata,
        content=content,
        content_hash=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
    )


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _stripped(text: str, offset: int) -> tuple[str, int]:
    """Return text.strip() and the offset at which the stripped text starts."""
    return text.strip(), offset + len(text) - len(text.lstrip())


def _split_between(pattern: re.Pattern[str], text: str, offset: int) -> list[tuple[str, int]]:
    """Like pattern.split(text), with each part paired with its offset."""
    parts: list[tuple[str, int]] = []
    position = 0
    for separator in pattern.finditer(text):
        parts.append((text[position : separator.start()], offset + position))
        position = separator.end()
    parts.append((text[position:], offset + position))
    return parts


def _split_oversized_block(block: str, offset: int, max_chars: int) -> list[tuple[str, int]]:
    """Split a block into pieces, each paired with its offset in the processing content."""
    lines: list[tuple[str, int]] = []
    position = offset
    for raw_line in block.splitlines(keepends=True):
        line, line_offset = _stripped(raw_line, position)
        if line:
            lines.append((line, line_offset))
        position += len(raw_line)
    pieces: list[tuple[str, int]] = []
    for line, line_offset in lines or [_stripped(block, offset)]:
        if len(line) <= max_chars:
            pieces.append((line, line_offset))
            continue
        for part, part_offset in _split_between(SENTENCE_BREAK_PATTERN, line, line_offset):
            sentence, sentence_offset = _stripped(part, part_offset)
            if not sentence:
                continue
            if len(sentence) <= max_chars:
                pieces.append((sentence, sentence_offset))
            else:
                pieces.extend(
                    (sentence[index : index + max_chars], sentence_offset + index)
                    for index in range(0, len(sentence), max_chars)
                )
    return pieces


def chunk_source(
    source: SourceNote,
    *,
    content: str | None = None,
    max_chars: int = DEFAULT_MAX_CHUNK_CHARS,
    overlap_chars: int = DEFAULT_CHUNK_OVERLAP_CHARS,
) -> list[SourceChunk]:
    if max_chars < 1_000:
        raise ValueError("max_chars must be at least 1000")
    if not 0 <= overlap_chars < max_chars:
        raise ValueError("overlap_chars must be non-negative and smaller than max_chars")

    processing_content = source.content if content is None else content
    # Every block carries its offset so a chunk can report where it sits in the content.
    blocks: list[tuple[str, int]] = []
    for part, part_offset in _split_between(BLOCK_SEPARATOR_PATTERN, processing_content, 0):
        block, block_offset = _stripped(part, part_offset)
        if not block:
            continue
        blocks.extend(_split_oversized_block(block, block_offset, max_chars))

    def joined(parts: list[tuple[str, int]]) -> str:
        return "\n\n".join(text for text, _offset in parts)

    chunk_parts: list[list[tuple[str, int]]] = []
    current: list[tuple[str, int]] = []
    current_length = 0
    for block in blocks:
        block_length = len(block[0])
        separator_length = 2 if current else 0
        if current and current_length + separator_length + block_length > max_chars:
            chunk_parts.append(current)
            overlap: list[tuple[str, int]] = []
            overlap_length = 0
            for previous in reversed(current):
                added = len(previous[0]) + (2 if overlap else 0)
                if overlap_length + added > overlap_chars:
                    break
                overlap.insert(0, previous)
                overlap_length += added
            current = overlap
            current_length = len(joined(current))
            if current and current_length + 2 + block_length > max_chars:
                current = []
                current_length = 0
        if current:
            current_length += 2
        current.append(block)
        current_length += block_length
    if current:
        if not chunk_parts or joined(current) != joined(chunk_parts[-1]):
            chunk_parts.append(current)

    chunks: list[SourceChunk] = []
    for index, parts in enumerate(chunk_parts, start=1):
        text = joined(parts)
        digest = hashlib.sha256(
            f"{source.content_hash}:{index}:{text}".encode("utf-8")
        ).hexdigest()[:16]
        last_text, last_offset = parts[-1]
        chunks.append(
            SourceChunk(
                source=source,
                index=index,
                identifier=f"chunk-{index:04d}-{digest}",
                text=text,
                start=parts[0][1],
                end=last_offset + len(last_text),
            )
        )
    return chunks
