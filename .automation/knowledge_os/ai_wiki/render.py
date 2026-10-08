from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

from .models import (
    Concept,
    Evidence,
    ExistingConcept,
    ProtectedNoteError,
    VerifiedNoteError,
)
from .schema import concept_identity, sanitize_concept_title
from .source import parse_markdown_frontmatter


MANAGED_PROPERTIES = {
    "type",
    "origin",
    "knowledge_status",
    "domain",
    "created",
    "updated",
    "sources",
    "human_verified",
}


def _date_string(value: Any) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()[:10]
    return str(value or "")


def _sections(body: str) -> dict[str, str]:
    matches = list(re.finditer(r"(?m)^##[ \t]+(.+?)[ \t]*$", body))
    result: dict[str, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        result[match.group(1).strip()] = body[match.end() : end].strip()
    return result


def _bullet_values(text: str) -> list[str]:
    values: list[str] = []
    for line in text.splitlines():
        match = re.match(r"^[ \t]*-[ \t]+(.+?)\s*$", line)
        if match:
            value = match.group(1).strip()
            wikilink = re.fullmatch(r"\[\[([^\]]+)\]\]", value)
            if wikilink:
                value = wikilink.group(1)
            value = re.sub(r"[ \t]+\(suggested\)$", "", value)
            values.append(value)
    return values


def _parse_evidence(text: str) -> list[Evidence]:
    matches = list(re.finditer(r"(?m)^###[ \t]+Evidence[ \t]+\d+[ \t]*$", text))
    evidence: list[Evidence] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        block = text[match.end() : end]
        fields: dict[str, str] = {}
        for line in block.splitlines():
            field_match = re.match(
                r"^[ \t]*-[ \t]+(Claim|Source|Excerpt|Chunk):[ \t]*(.*?)\s*$",
                line,
            )
            if field_match:
                fields[field_match.group(1)] = field_match.group(2)
        if fields.get("Claim") and fields.get("Excerpt"):
            chunk = fields.get("Chunk", "").strip("`")
            evidence.append(
                Evidence(
                    claim=fields["Claim"],
                    source_excerpt=fields["Excerpt"],
                    source_link=fields.get("Source", ""),
                    chunk_id=chunk,
                )
            )
    return evidence


def load_existing_concept(path: Path) -> ExistingConcept:
    try:
        original = path.read_text(encoding="utf-8")
        metadata, body = parse_markdown_frontmatter(original)
    except Exception as exc:
        if isinstance(exc, ProtectedNoteError):
            raise
        raise ProtectedNoteError(f"cannot safely parse existing note {path.name}: {exc}") from exc

    if metadata.get("type") != "concept":
        raise ProtectedNoteError(f"existing target {path.name} is not type: concept")
    if metadata.get("origin") != "ai":
        raise ProtectedNoteError(f"existing target {path.name} is not origin: ai")
    if metadata.get("knowledge_status") != "processed":
        raise ProtectedNoteError(
            f"existing target {path.name} is not knowledge_status: processed"
        )
    if metadata.get("human_verified") is not False:
        raise VerifiedNoteError(f"existing target {path.name} is human-verified")
    missing = MANAGED_PROPERTIES - set(metadata)
    if missing:
        raise ProtectedNoteError(
            f"existing target {path.name} is missing managed properties: "
            f"{', '.join(sorted(missing))}"
        )

    title_match = re.search(r"(?m)^#[ \t]+(.+?)[ \t]*$", body)
    title = sanitize_concept_title(title_match.group(1) if title_match else path.stem)
    sections = _sections(body)
    sources = metadata.get("sources", [])
    domains = metadata.get("domain", [])
    if not isinstance(sources, list) or not all(isinstance(item, str) for item in sources):
        raise ProtectedNoteError(f"existing target {path.name} has invalid sources")
    if not isinstance(domains, list) or not all(isinstance(item, str) for item in domains):
        raise ProtectedNoteError(f"existing target {path.name} has invalid domain")

    concept = Concept(
        title=title,
        definition=sections.get("Definition", ""),
        core_idea=sections.get("Core Idea", ""),
        mechanism=sections.get("Mechanism", ""),
        key_points=_bullet_values(sections.get("Key Points", "")),
        related_concepts=_bullet_values(sections.get("Related Concepts", "")),
        evidence=_parse_evidence(sections.get("Evidence", "")),
        open_questions=_bullet_values(sections.get("Open Questions", "")),
        domain=list(domains),
        sources=list(sources),
    )
    return ExistingConcept(
        path=path,
        concept=concept,
        metadata=metadata,
        created=_date_string(metadata.get("created")),
        original_text=original,
    )


def _single_line(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _section_text(value: str) -> str:
    return value.strip()


def _bullets(values: list[str]) -> str:
    return "\n".join(f"- {_single_line(value)}" for value in values)


def _related_bullets(values: list[str], known_titles: dict[str, str]) -> str:
    lines: list[str] = []
    for value in values:
        identity = concept_identity(value)
        if identity in known_titles:
            lines.append(f"- [[{known_titles[identity]}]]")
        else:
            lines.append(f"- {_single_line(value)} (suggested)")
    return "\n".join(lines)


def _evidence_markdown(values: list[Evidence]) -> str:
    blocks: list[str] = []
    for index, value in enumerate(values, start=1):
        lines = [
            f"### Evidence {index}",
            f"- Claim: {_single_line(value.claim)}",
            f"- Source: {value.source_link}",
            f"- Excerpt: {_single_line(value.source_excerpt)}",
        ]
        if value.chunk_id:
            lines.append(f"- Chunk: `{value.chunk_id}`")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def render_concept_note(
    concept: Concept,
    *,
    created: str,
    updated: str,
    provider_name: str,
    model_name: str,
    known_titles: dict[str, str],
    existing_metadata: dict[str, Any] | None = None,
) -> str:
    metadata: dict[str, Any] = {
        "type": "concept",
        "origin": "ai",
        "knowledge_status": "processed",
        "domain": concept.domain,
        "created": created,
        "updated": updated,
        "sources": concept.sources,
        "human_verified": False,
    }
    if existing_metadata:
        for key, value in existing_metadata.items():
            if key not in MANAGED_PROPERTIES:
                metadata[key] = value

    frontmatter = yaml.safe_dump(
        metadata,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
        width=1000,
    ).strip()
    source_bullets = _bullets(concept.sources)
    provenance = (
        f"- Backend: `{provider_name}`\n"
        f"- Model: `{model_name}`\n"
        f"- Evidence sources: {', '.join(concept.sources)}"
    )
    return (
        f"---\n{frontmatter}\n---\n\n"
        f"# {concept.title}\n\n"
        "> AI-generated knowledge. Verify against original sources before treating as understood.\n\n"
        "## Definition\n\n"
        f"{_section_text(concept.definition)}\n\n"
        "## Core Idea\n\n"
        f"{_section_text(concept.core_idea)}\n\n"
        "## Mechanism\n\n"
        f"{_section_text(concept.mechanism)}\n\n"
        "## Key Points\n\n"
        f"{_bullets(concept.key_points)}\n\n"
        "## Related Concepts\n\n"
        f"{_related_bullets(concept.related_concepts, known_titles)}\n\n"
        "## Evidence\n\n"
        f"{_evidence_markdown(concept.evidence)}\n\n"
        "## Sources\n\n"
        f"{source_bullets}\n\n"
        "## Open Questions\n\n"
        f"{_bullets(concept.open_questions)}\n\n"
        "## Provenance\n\n"
        f"{provenance}\n"
    )


def classify_relation(existing: Concept, incoming: Concept) -> str:
    existing_text = " ".join(
        [existing.definition, existing.core_idea, existing.mechanism, *existing.key_points]
    ).casefold()
    incoming_text = " ".join(
        [incoming.definition, incoming.core_idea, incoming.mechanism, *incoming.key_points]
    ).casefold()

    def negations(text: str) -> set[str]:
        return {
            re.sub(r"\s+", " ", match.group(1)).strip()
            for match in re.finditer(r"\bnot\s+([^.!?]+)", text)
        }

    existing_negations = negations(existing_text)
    incoming_negations = negations(incoming_text)
    if any(
        value
        and value in existing_text
        and f"not {value}" not in existing_text
        for value in incoming_negations
    ):
        return "contradicts"
    if any(
        value
        and value in incoming_text
        and f"not {value}" not in incoming_text
        for value in existing_negations
    ):
        return "contradicts"

    existing_values = {
        _single_line(value).casefold()
        for value in [
            existing.definition,
            existing.core_idea,
            existing.mechanism,
            *existing.key_points,
        ]
        if value.strip()
    }
    incoming_values = {
        _single_line(value).casefold()
        for value in [
            incoming.definition,
            incoming.core_idea,
            incoming.mechanism,
            *incoming.key_points,
        ]
        if value.strip()
    }
    if incoming_values.issubset(existing_values):
        return "supports"
    return "extends"
