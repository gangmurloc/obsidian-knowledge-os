"""Relates candidate evidence to method subsections.

``uncovered_method_subsections`` decides which subsections get a targeted extraction
call. ``build_method_coverage`` is a read-only report; its output contains identifiers,
headings, titles, roles, and counts, never Source text.
"""

from __future__ import annotations

import unicodedata
from bisect import bisect_right
from collections.abc import Collection, Mapping, Sequence

from .models import Concept, SourceChunk
from .preprocess import OMISSION_MARKER_PATTERN, MethodSubsection
from .quality import candidate_matches_methodology_subsection


MAX_SUBSECTION_ROWS = 20
MAX_IN_SPAN_CANDIDATES = 5
COVER_ROLES = {"mechanism", "component"}
EMPHASIS_CHARACTERS = frozenset("*_`")
Range = tuple[int, int]


def _continues_cluster(character: str) -> bool:
    # Combining marks and Hangul medial/final jamo compose with the character before them.
    return bool(unicodedata.combining(character)) or "ᅠ" <= character <= "ᇿ"


def _normalize_with_offsets(text: str) -> tuple[str, list[int], list[int]]:
    """NFKC, casefold, drop Markdown emphasis, and collapse whitespace.

    Returns the normalized text plus, for each of its characters, the start and end
    offset in ``text`` of the characters it came from.
    """
    characters: list[str] = []
    starts: list[int] = []
    ends: list[int] = []
    index = 0
    while index < len(text):
        end = index + 1
        while end < len(text) and _continues_cluster(text[end]):
            end += 1
        for character in unicodedata.normalize("NFKC", text[index:end]).casefold():
            if character in EMPHASIS_CHARACTERS:
                continue
            if character.isspace():
                if characters and characters[-1] == " ":
                    continue
                character = " "
            characters.append(character)
            starts.append(index)
            ends.append(end)
        index = end
    return "".join(characters), starts, ends


class ExcerptLocator:
    """Finds excerpts in one processing view, which is normalized only once."""

    def __init__(self, content: str) -> None:
        self._normalized, self._starts, self._ends = _normalize_with_offsets(content)
        self._marker_starts: list[int] = []
        self._marker_ends: list[int] = []
        offset = 0
        for line in content.splitlines(keepends=True):
            if OMISSION_MARKER_PATTERN.match(line):
                self._marker_starts.append(offset)
                self._marker_ends.append(offset + len(line))
            offset += len(line)

    def _inside_omission_marker(self, start: int, end: int) -> bool:
        index = bisect_right(self._marker_starts, start) - 1
        return index >= 0 and end <= self._marker_ends[index]

    def locate(self, excerpt: str, *, preferred_range: Range | None = None) -> Range | None:
        """Return the excerpt's range in the original content, or None.

        Matching is exact after normalization; there is no fuzzy matching. A match
        inside ``preferred_range`` wins, otherwise the first match is used. Text that
        occurs only inside an omission marker is not located.
        """
        needle = _normalize_with_offsets(excerpt)[0].strip()
        if not needle:
            return None
        first: Range | None = None
        position = self._normalized.find(needle)
        while position != -1:
            start = self._starts[position]
            end = self._ends[position + len(needle) - 1]
            if not self._inside_omission_marker(start, end):
                if preferred_range is None:
                    return start, end
                if preferred_range[0] <= start and end <= preferred_range[1]:
                    return start, end
                if first is None:
                    first = (start, end)
            position = self._normalized.find(needle, position + 1)
        return first


def locate_excerpt(
    excerpt: str,
    content: str,
    *,
    preferred_range: Range | None = None,
) -> Range | None:
    return ExcerptLocator(content).locate(excerpt, preferred_range=preferred_range)


def _located_evidence_starts(
    content: str,
    chunks: Sequence[SourceChunk],
    candidates: Mapping[str, Concept],
) -> dict[str, list[int]]:
    """Start offsets of every candidate's evidence that can be located, by identity."""
    locator = ExcerptLocator(content)
    chunk_ranges = {
        chunk.identifier: (chunk.start, chunk.end)
        for chunk in chunks
        if chunk.start is not None and chunk.end is not None
    }
    starts: dict[str, list[int]] = {}
    for identity, concept in candidates.items():
        located = (
            locator.locate(item.source_excerpt, preferred_range=chunk_ranges.get(item.chunk_id))
            for item in concept.evidence
        )
        starts[identity] = [position[0] for position in located if position is not None]
    return starts


def _evidence_in_span(subsection: MethodSubsection, starts: Sequence[int]) -> int:
    return sum(subsection.start <= start < subsection.end for start in starts)


def _cover(
    subsection: MethodSubsection,
    identities: Collection[str],
    *,
    candidates: Mapping[str, Concept],
    evidence_starts: Mapping[str, Sequence[int]],
    source_title: object,
) -> tuple[bool, bool]:
    """Whether a mechanism or component covers the subsection by title and by evidence."""
    concepts = [
        (identity, candidates[identity])
        for identity in identities
        if identity in candidates and candidates[identity].role in COVER_ROLES
    ]
    title_cover = any(
        candidate_matches_methodology_subsection(
            concept,
            source_title=source_title,
            methodology_subsections=(subsection.canonical_heading,),
        )
        for _identity, concept in concepts
    )
    evidence_cover = any(
        _evidence_in_span(subsection, evidence_starts.get(identity, ()))
        for identity, _concept in concepts
    )
    return title_cover, evidence_cover


def uncovered_method_subsections(
    *,
    content: str,
    subsections: Sequence[MethodSubsection],
    chunks: Sequence[SourceChunk],
    candidates: Mapping[str, Concept],
    source_title: object,
) -> list[MethodSubsection]:
    """Subsections that no mechanism or component covers by title or by located evidence."""
    if not subsections:
        return []
    evidence_starts = _located_evidence_starts(content, chunks, candidates)
    return [
        subsection
        for subsection in subsections
        if not any(
            _cover(
                subsection,
                candidates,
                candidates=candidates,
                evidence_starts=evidence_starts,
                source_title=source_title,
            )
        )
    ]


def method_subsection_evidence(
    *,
    content: str,
    subsections: Sequence[MethodSubsection],
    chunks: Sequence[SourceChunk],
    candidates: Mapping[str, Concept],
) -> dict[str, tuple[str, ...]]:
    """For each candidate, the method subsections whose span holds its located evidence."""
    if not subsections:
        return {}
    evidence_starts = _located_evidence_starts(content, chunks, candidates)
    return {
        identity: tuple(
            dict.fromkeys(
                subsection.canonical_heading
                for subsection in subsections
                if _evidence_in_span(subsection, starts)
            )
        )
        for identity, starts in evidence_starts.items()
    }


def _numbers(values: Sequence[int]) -> str:
    return ",".join(str(value) for value in values) or "-"


def _flag(value: bool) -> str:
    return "y" if value else "n"


def build_method_coverage(
    *,
    source_label: str,
    content: str,
    subsections: Sequence[MethodSubsection],
    chunks: Sequence[SourceChunk],
    heading_chunks: Mapping[str, Sequence[int]],
    candidates: Mapping[str, Concept],
    selected: Collection[str],
    source_title: object,
    targeted_chunks: Sequence[SourceChunk] = (),
) -> tuple[list[str], str]:
    """Return the ``method_coverage`` rows and the ``evidence_locatability`` line.

    ``candidates`` is every candidate after role assignment, keyed by identity, and
    ``selected`` holds the identities that survived selection. A subsection is
    title-covered by the existing quality-gate rule and evidence-covered when a
    mechanism or component has located evidence that starts inside its span.
    ``targeted_chunks`` only helps place evidence that a targeted call produced.
    """
    evidence_starts = _located_evidence_starts(
        content,
        [*chunks, *targeted_chunks],
        candidates,
    )
    evidence_total = sum(len(concept.evidence) for concept in candidates.values())
    located_total = sum(len(starts) for starts in evidence_starts.values())
    locatability = (
        f"{source_label}: located {located_total}/{evidence_total} evidence "
        f"across {len(candidates)} candidates"
    )
    if not subsections:
        return [f"{source_label}: no methodology subsections detected"], locatability

    rows: list[str] = []
    for subsection in subsections[:MAX_SUBSECTION_ROWS]:
        entries = [
            f"{candidates[identity].title}({candidates[identity].role}, "
            f"located {count}/{len(candidates[identity].evidence)})"
            for identity, starts in sorted(evidence_starts.items())
            if (count := _evidence_in_span(subsection, starts))
        ]
        shown = entries[:MAX_IN_SPAN_CANDIDATES]
        if len(entries) > len(shown):
            shown.append(f"+{len(entries) - len(shown)} more")
        offset_chunks = [
            chunk.index
            for chunk in chunks
            if chunk.start is not None
            and chunk.end is not None
            and chunk.start < subsection.end
            and subsection.start < chunk.end
        ]
        cover = {
            label: _cover(
                subsection,
                identities,
                candidates=candidates,
                evidence_starts=evidence_starts,
                source_title=source_title,
            )
            for label, identities in (("candidates", candidates), ("selected", selected))
        }
        rows.append(
            f"{source_label}: [{subsection.subsection_id}] {subsection.canonical_heading} "
            f"pages={_numbers(subsection.pages)} "
            f"heading_chunks={_numbers(heading_chunks.get(subsection.subsection_id, ()))} "
            f"offset_chunks={_numbers(offset_chunks)} "
            + "".join(
                f"| {label}: title_cover={_flag(title)} evidence_cover={_flag(evidence)} "
                for label, (title, evidence) in cover.items()
            )
            + f"| in_span: {', '.join(shown) or '(none)'}"
        )
    if len(subsections) > MAX_SUBSECTION_ROWS:
        rows.append(f"{source_label}: ... (+{len(subsections) - MAX_SUBSECTION_ROWS} more)")
    return rows, locatability
