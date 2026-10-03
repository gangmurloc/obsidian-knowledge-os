from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .curator import (
    DuplicateRiskGroup,
    concept_comparison_signatures,
    is_source_branded_identity,
)
from .models import Concept
from .ontology import concept_identity


SOURCE_ENTITY_DOMINANCE_RATIO = 2 / 3
MIN_NAMED_METHOD_SUBSECTIONS = 2


@dataclass(frozen=True)
class QualityAssessment:
    status: str
    reasons: tuple[str, ...]


def candidate_matches_methodology_subsection(
    concept: Concept,
    *,
    source_title: object,
    methodology_subsections: Iterable[str],
) -> bool:
    signatures = concept_comparison_signatures(
        concept.title,
        source_title=source_title,
    )
    return any(
        concept_identity(heading) in signatures for heading in methodology_subsections
    )


def _is_source_entity_like(concept: Concept, *, source_title: object) -> bool:
    return concept.is_primary_source_entity or (
        concept.role == "method_entity"
        and is_source_branded_identity(
            concept.title,
            source_title=source_title,
        )
    )


def source_entity_dominance(
    concepts: dict[str, Concept], *, source_title: object
) -> tuple[bool, int, int]:
    total = len(concepts)
    entity_count = sum(
        _is_source_entity_like(concept, source_title=source_title)
        for concept in concepts.values()
    )
    dominant = bool(
        total
        and entity_count >= 2
        and entity_count / total >= SOURCE_ENTITY_DOMINANCE_RATIO
    )
    return dominant, entity_count, total


def explicit_method_coverage_failure(
    concepts: dict[str, Concept],
    *,
    source_title: object,
    methodology_subsections: Iterable[str],
) -> bool:
    headings = tuple(methodology_subsections)
    if len(headings) < MIN_NAMED_METHOD_SUBSECTIONS:
        return False
    return not any(
        concept.role in {"mechanism", "component"}
        and candidate_matches_methodology_subsection(
            concept,
            source_title=source_title,
            methodology_subsections=headings,
        )
        for concept in concepts.values()
    )


def evaluate_quality_gate(
    concepts: dict[str, Concept],
    *,
    source_title: object,
    methodology_subsections: Iterable[str],
    duplicate_risk_groups: Iterable[DuplicateRiskGroup],
) -> QualityAssessment:
    reasons: list[str] = []
    primary_count = sum(
        concept.is_primary_source_entity for concept in concepts.values()
    )
    if primary_count > 1:
        reasons.append(
            f"multiple primary source entities selected: {primary_count}"
        )
    dominant, entity_count, total = source_entity_dominance(
        concepts,
        source_title=source_title,
    )
    if dominant:
        reasons.append(
            f"excessive source-entity dominance: {entity_count}/{total} selected concepts"
        )

    selected = set(concepts)
    unresolved_groups = [
        group
        for group in duplicate_risk_groups
        if len(selected.intersection(group.identities)) > 1
    ]
    if unresolved_groups:
        reasons.append(
            f"unresolved duplicate-risk after curation: {len(unresolved_groups)} group(s)"
        )

    headings = tuple(methodology_subsections)
    if explicit_method_coverage_failure(
        concepts,
        source_title=source_title,
        methodology_subsections=headings,
    ):
        reasons.append(
            "explicit methodology mechanisms detected but none selected"
        )

    if concepts and all(
        _is_source_entity_like(concept, source_title=source_title)
        for concept in concepts.values()
    ):
        reasons.append("only generic/source-name concepts selected")

    return QualityAssessment(
        status="failed" if reasons else "pass",
        reasons=tuple(reasons),
    )
