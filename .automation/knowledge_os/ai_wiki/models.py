from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class AIWikiError(RuntimeError):
    """Base error for AI-Wiki processing failures."""


class SourceValidationError(AIWikiError):
    """A source note is not safe or complete enough to process."""


class StructuredOutputError(AIWikiError):
    """The Local LLM returned output outside the extraction schema."""


class MalformedJSONError(StructuredOutputError):
    """The Local LLM response is not syntactically valid JSON."""


class ProtectedNoteError(AIWikiError):
    """A target note is human-owned or otherwise outside the write boundary."""


@dataclass(frozen=True)
class SourceNote:
    path: Path
    relative_path: str
    note_name: str
    metadata: dict[str, Any]
    content: str
    content_hash: str

    @property
    def link(self) -> str:
        return f"[[{self.note_name}]]"


@dataclass(frozen=True)
class SourceChunk:
    source: SourceNote
    index: int
    identifier: str
    text: str


@dataclass(frozen=True)
class Evidence:
    claim: str
    source_excerpt: str
    source_link: str = ""
    chunk_id: str = ""


@dataclass
class Concept:
    title: str
    definition: str
    core_idea: str
    mechanism: str
    key_points: list[str] = field(default_factory=list)
    related_concepts: list[str] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    domain: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)


@dataclass
class ExistingConcept:
    path: Path
    concept: Concept
    metadata: dict[str, Any]
    created: str
    original_text: str


@dataclass(frozen=True)
class PlannedChange:
    action: str
    title: str
    path: Path
    relation: str | None
    content: str | None


@dataclass(frozen=True)
class RelationSuggestion:
    subject: str
    relation: str
    object: str
    reason: str


@dataclass
class ProcessingStats:
    source_characters: int = 0
    chunk_count: int = 0
    chunk_characters: int = 0
    maximum_chunk_size: int = 0
    llm_calls: int = 0
    json_repairs: int = 0
    timeout_failures: int = 0

    @property
    def average_chunk_size(self) -> float:
        if not self.chunk_count:
            return 0.0
        return self.chunk_characters / self.chunk_count


@dataclass
class ProcessingPlan:
    processed_sources: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    removed_sources: list[str] = field(default_factory=list)
    changes: list[PlannedChange] = field(default_factory=list)
    relation_suggestions: list[RelationSuggestion] = field(default_factory=list)
    state_updates: dict[str, dict[str, Any]] = field(default_factory=dict)
    stats: ProcessingStats = field(default_factory=ProcessingStats)

    @property
    def changed_notes(self) -> list[PlannedChange]:
        return [change for change in self.changes if change.action in {"create", "update"}]
