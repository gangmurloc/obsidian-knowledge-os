"""Check an AI-Wiki note against its Sources and record a delegated review.

The vault owner decided on 2026-10-06 that an AI reviewer may set
``human_verified: true`` on AI-Wiki notes. So that the flag stays truthful, a note
marked here also gets ``verified_by: ai`` and a provenance line naming the reviewer.
Scan and apply never set the flag; only this explicit step does.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from ..io_utils import atomic_write_text
from .coverage import ExcerptLocator
from .engine import AI_WIKI_RELATIVE_PATH, _assert_ai_wiki_path, _source_paths
from .models import AIWikiError, ProtectedNoteError
from .preprocess import build_ai_processing_view
from .render import load_existing_concept
from .source import FRONTMATTER_PATTERN, load_source_note, parse_markdown_frontmatter


REVIEWER_PATTERN = re.compile(r"[^\[\]<>`\r\n]{1,80}")
WIKILINK_PATTERN = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")
UNVERIFIED_LINE_PATTERN = re.compile(r"(?m)^human_verified:[ \t]*false[ \t]*$")


@dataclass(frozen=True)
class NoteCheck:
    relative_path: str
    title: str
    sources: tuple[str, ...]
    evidence_total: int
    evidence_located: int
    evidence_not_found: tuple[int, ...]
    status: str


def _mark_verified(text: str, *, reviewer: str, today: str, located: int, total: int) -> str:
    """Flip the flag and add the review record; every other byte of the note is kept."""
    frontmatter = FRONTMATTER_PATTERN.match(text)
    if frontmatter is None:
        raise AIWikiError("note has no YAML frontmatter")
    properties = re.sub(r"(?m)^verified_by:.*\n?", "", frontmatter.group("yaml"))
    properties, replaced = UNVERIFIED_LINE_PATTERN.subn(
        "human_verified: true\nverified_by: ai",
        properties,
    )
    if replaced != 1:
        raise AIWikiError("note does not have exactly one 'human_verified: false' line")
    text = text[: frontmatter.start("yaml")] + properties + text[frontmatter.end("yaml") :]

    record = (
        f"- Verification: reviewed by {reviewer} (AI) on {today}; "
        f"{located} of {total} evidence excerpts found verbatim in the Source."
    )
    heading = re.search(r"(?m)^##[ \t]+Provenance[ \t]*$", text)
    if heading is None:
        return f"{text.rstrip()}\n\n## Provenance\n\n{record}\n"
    following = re.search(r"(?m)^##[ \t]+", text[heading.end() :])
    section_end = heading.end() + following.start() if following else len(text)
    section = text[heading.end() : section_end].rstrip("\n")
    rest = f"\n{text[section_end:]}" if following else ""
    return f"{text[: heading.end()]}{section}\n{record}\n{rest}"


def check_note(
    *,
    vault_root: Path,
    note: str,
    reviewer: str | None = None,
    write: bool = False,
    today: date | None = None,
) -> NoteCheck:
    """Report how a note's evidence matches its Sources and, with ``write``, mark it."""
    root = vault_root.resolve()
    output_root = (root / AI_WIKI_RELATIVE_PATH).resolve()
    name = note if note.casefold().endswith(".md") else f"{note}.md"
    path = output_root / name
    _assert_ai_wiki_path(path, output_root)
    if not path.is_file():
        raise AIWikiError(f"AI-Wiki note not found: {name}")
    relative = path.relative_to(root).as_posix()
    text = path.read_text(encoding="utf-8")
    metadata, _body = parse_markdown_frontmatter(text)
    if metadata.get("type") != "concept" or metadata.get("origin") != "ai":
        raise ProtectedNoteError(f"{name} is not an AI-owned concept note")
    if metadata.get("human_verified") is True:
        return NoteCheck(relative, path.stem, (), 0, 0, (), "already verified")

    existing = load_existing_concept(path)
    concept = existing.concept
    source_paths = {source.stem.casefold(): source for source in _source_paths(root)}
    locators: dict[str, ExcerptLocator] = {}

    def locator_for(link: str) -> ExcerptLocator:
        match = WIKILINK_PATTERN.fullmatch(link.strip())
        if match is None:
            raise AIWikiError(f"{name} has an unreadable Source link: {link!r}")
        key = match.group(1).strip().casefold()
        if key not in locators:
            source_path = source_paths.get(key)
            if source_path is None:
                raise AIWikiError(f"{name} cites a Source that does not exist: {link}")
            source = load_source_note(source_path, root)
            locators[key] = ExcerptLocator(build_ai_processing_view(source.content).content)
        return locators[key]

    if not concept.sources:
        raise AIWikiError(f"{name} cites no Source")
    for link in concept.sources:
        locator_for(link)
    not_found = tuple(
        number
        for number, item in enumerate(concept.evidence, start=1)
        if locator_for(item.source_link or concept.sources[0]).locate(item.source_excerpt) is None
    )
    total = len(concept.evidence)
    located = total - len(not_found)

    status = "checked"
    if write:
        if reviewer is None or REVIEWER_PATTERN.fullmatch(reviewer.strip()) is None:
            raise AIWikiError("a reviewer name of 1 to 80 plain characters is required to mark a note")
        marked = _mark_verified(
            text,
            reviewer=reviewer.strip(),
            today=(today or date.today()).isoformat(),
            located=located,
            total=total,
        )
        marked_metadata, _marked_body = parse_markdown_frontmatter(marked)
        if marked_metadata.get("human_verified") is not True or marked_metadata.get("verified_by") != "ai":
            raise AIWikiError(f"could not mark {name} safely; the note was left unchanged")
        atomic_write_text(path, marked, overwrite=True)
        status = "marked"
    return NoteCheck(
        relative_path=relative,
        title=concept.title,
        sources=tuple(concept.sources),
        evidence_total=total,
        evidence_located=located,
        evidence_not_found=not_found,
        status=status,
    )
