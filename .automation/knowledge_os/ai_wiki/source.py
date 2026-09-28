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


def _split_oversized_block(block: str, max_chars: int) -> list[str]:
    lines = [line.strip() for line in block.splitlines() if line.strip()]
    pieces: list[str] = []
    for line in lines or [block.strip()]:
        if len(line) <= max_chars:
            pieces.append(line)
            continue
        sentences = re.split(r"(?<=[.!?。！？])\s+", line)
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            if len(sentence) <= max_chars:
                pieces.append(sentence)
            else:
                pieces.extend(
                    sentence[index : index + max_chars]
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
    raw_blocks = [block.strip() for block in re.split(r"\n[ \t]*\n", processing_content)]
    blocks: list[str] = []
    for block in raw_blocks:
        if not block:
            continue
        blocks.extend(_split_oversized_block(block, max_chars))

    chunk_texts: list[str] = []
    current: list[str] = []
    current_length = 0
    for block in blocks:
        separator_length = 2 if current else 0
        if current and current_length + separator_length + len(block) > max_chars:
            chunk_texts.append("\n\n".join(current))
            overlap: list[str] = []
            overlap_length = 0
            for previous in reversed(current):
                added = len(previous) + (2 if overlap else 0)
                if overlap_length + added > overlap_chars:
                    break
                overlap.insert(0, previous)
                overlap_length += added
            current = overlap
            current_length = len("\n\n".join(current))
            if current and current_length + 2 + len(block) > max_chars:
                current = []
                current_length = 0
        if current:
            current_length += 2
        current.append(block)
        current_length += len(block)
    if current:
        text = "\n\n".join(current)
        if not chunk_texts or text != chunk_texts[-1]:
            chunk_texts.append(text)

    chunks: list[SourceChunk] = []
    for index, text in enumerate(chunk_texts, start=1):
        digest = hashlib.sha256(
            f"{source.content_hash}:{index}:{text}".encode("utf-8")
        ).hexdigest()[:16]
        chunks.append(
            SourceChunk(
                source=source,
                index=index,
                identifier=f"chunk-{index:04d}-{digest}",
                text=text,
            )
        )
    return chunks
