from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

from .models import Concept, RelationSuggestion, StructuredOutputError


LEADING_ARTICLES = {"a", "an", "the"}
STRUCTURE_IDENTITIES = {
    "abstract",
    "acknowledgements",
    "acknowledgments",
    "appendix",
    "background",
    "conclusion",
    "conclusions",
    "discussion",
    "introduction",
    "method",
    "methodology",
    "methods",
    "references",
    "related work",
    "result",
    "results",
}
CONTEXT_CONNECTORS = {"for", "in", "of", "on", "to", "with"}
NUMBERED_STRUCTURE_PATTERN = re.compile(
    r"^(?:table|figure|fig|section)\s+(?:\d+(?:\.\d+)*|[ivxlcdm]+)(?:\s+.*)?$",
    re.IGNORECASE,
)
CANONICAL_PHRASES = (
    (re.compile(r"\bself[\s-]+attention\b", re.IGNORECASE), "Self-Attention"),
    (
        re.compile(r"\bmulti[\s-]+head(?:ed)?[\s-]+attention\b", re.IGNORECASE),
        "Multi-Head Attention",
    ),
    (
        re.compile(
            r"\bscaled[\s-]+dot[\s-]+product[\s-]+attention\b",
            re.IGNORECASE,
        ),
        "Scaled Dot-Product Attention",
    ),
    (re.compile(r"\bfeed[\s-]+forward\b", re.IGNORECASE), "Feed-Forward"),
)


def _identity_tokens(value: str, *, drop_leading_article: bool = True) -> list[str]:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    tokens = re.findall(r"[^\W_]+", normalized, flags=re.UNICODE)
    if drop_leading_article and len(tokens) > 1 and tokens[0] in LEADING_ARTICLES:
        tokens = tokens[1:]
    return tokens


def concept_identity(title: str) -> str:
    return " ".join(_identity_tokens(title))


def _smart_english_title(value: str) -> str:
    ascii_letters = re.findall(r"[A-Za-z]", value)
    if not ascii_letters or any(character.isupper() for character in ascii_letters):
        return value
    small_words = {"and", "for", "in", "of", "on", "or", "the", "to", "with"}
    words = value.split(" ")
    result: list[str] = []
    for index, word in enumerate(words):
        if index > 0 and word in small_words:
            result.append(word)
            continue
        result.append("-".join(part.capitalize() for part in word.split("-")))
    return " ".join(result)


def canonicalize_concept_title(value: str) -> str:
    title = unicodedata.normalize("NFKC", value)
    title = "".join(character for character in title if ord(character) >= 32)
    title = re.sub(r"[<>\[\]#^|]", "", title)
    title = re.sub(r"\s*[-‐‑‒–—―]\s*", "-", title)
    title = re.sub(r"\s+", " ", title).strip(" .")
    title = re.sub(r"^(?:a|an|the)\s+", "", title, flags=re.IGNORECASE)
    title = _smart_english_title(title)
    for pattern, replacement in CANONICAL_PHRASES:
        title = pattern.sub(replacement, title)
    if not title:
        raise StructuredOutputError("concept title is empty after canonicalization")
    if len(title) > 120:
        raise StructuredOutputError("concept title exceeds 120 characters")
    return title


def concept_exclusion_reason(title: str, source_title: object) -> str | None:
    identity = concept_identity(title)
    if not identity:
        return "has an empty identity"
    if isinstance(source_title, str) and source_title.strip():
        if identity == concept_identity(source_title):
            return "matches the Source title"
    if identity in STRUCTURE_IDENTITIES or NUMBERED_STRUCTURE_PATTERN.fullmatch(identity):
        return "is a document structure heading"
    return None


def _contains_sequence(longer: list[str], shorter: list[str]) -> tuple[bool, int]:
    width = len(shorter)
    for index in range(len(longer) - width + 1):
        if longer[index : index + width] == shorter:
            return True, index
    return False, -1


def _pair_relation(left: Concept, right: Concept) -> RelationSuggestion | None:
    left_tokens = _identity_tokens(left.title)
    right_tokens = _identity_tokens(right.title)
    if not left_tokens or not right_tokens or left_tokens == right_tokens:
        return None

    shorter, longer = (left, right) if len(left_tokens) < len(right_tokens) else (right, left)
    shorter_tokens = _identity_tokens(shorter.title)
    longer_tokens = _identity_tokens(longer.title)
    contains, start = _contains_sequence(longer_tokens, shorter_tokens)
    if contains:
        before = longer_tokens[:start]
        after = longer_tokens[start + len(shorter_tokens) :]
        if (before and before[-1] in CONTEXT_CONNECTORS) or (
            after and after[0] in CONTEXT_CONNECTORS
        ):
            return RelationSuggestion(
                subject=longer.title,
                relation="related_to",
                object=shorter.title,
                reason="shared title phrase appears in a source-specific context",
            )
        return RelationSuggestion(
            subject=longer.title,
            relation="narrower_than",
            object=shorter.title,
            reason="the shorter normalized title is a complete phrase in the longer title",
        )

    overlap = set(left_tokens) & set(right_tokens)
    if len(overlap) >= 2 and len(overlap) / min(len(left_tokens), len(right_tokens)) >= 0.5:
        return RelationSuggestion(
            subject=left.title,
            relation="related_to",
            object=right.title,
            reason="normalized titles share multiple significant words",
        )
    return None


def suggest_relations(concepts: Iterable[Concept]) -> list[RelationSuggestion]:
    ordered = sorted(concepts, key=lambda concept: concept_identity(concept.title))
    suggestions: list[RelationSuggestion] = []
    for index, left in enumerate(ordered):
        for right in ordered[index + 1 :]:
            suggestion = _pair_relation(left, right)
            if suggestion is not None:
                suggestions.append(suggestion)
    return suggestions
