from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from ..io_utils import atomic_write_json, atomic_write_text
from ..llm import GenerateRequest, LLMProvider, ProviderTimeoutError
from .models import (
    AIWikiError,
    Concept,
    Evidence,
    ExistingConcept,
    MalformedJSONError,
    PlannedChange,
    ProcessingPlan,
    ProtectedNoteError,
    SourceValidationError,
    StructuredOutputError,
)
from .ontology import concept_exclusion_reason, suggest_relations
from .render import classify_relation, load_existing_concept, render_concept_note
from .schema import (
    CONCEPT_EXTRACTION_SCHEMA,
    build_extraction_prompt,
    build_json_repair_prompt,
    concept_filename,
    concept_identity,
    merge_concepts,
    parse_concept_response,
)
from .source import DEFAULT_MAX_CHUNK_CHARS, chunk_source, load_source_note


STATE_RELATIVE_PATH = Path(".automation/state/ai_wiki.json")
AI_WIKI_RELATIVE_PATH = Path("30_Resources/AI-Wiki")
SOURCE_ROOT_RELATIVE_PATH = Path("30_Resources/Sources")
MAX_CONCEPTS_PER_SOURCE = 12
AI_WIKI_MAX_OUTPUT_TOKENS = 1_024
DIAGNOSTICS_RELATIVE_PATH = Path(".automation/state/diagnostics")
MAX_DIAGNOSTIC_RESPONSE_CHARS = 256_000
THINK_BLOCK_PATTERN = re.compile(r"<think\b[^>]*>.*?</think>", re.IGNORECASE | re.DOTALL)


@dataclass(frozen=True)
class ScanScope:
    mode: str
    source: str | None = None

    def __post_init__(self) -> None:
        if self.mode not in {"source", "papers", "web", "all", "changed"}:
            raise ValueError(f"unsupported scan mode: {self.mode}")
        if self.mode == "source" and not self.source:
            raise ValueError("source mode requires a source filename")
        if self.mode != "source" and self.source is not None:
            raise ValueError("source can only be used with source mode")


def _source_paths(vault_root: Path) -> list[Path]:
    source_root = vault_root / SOURCE_ROOT_RELATIVE_PATH
    paths: list[Path] = []
    for directory_name in ("Papers", "Web"):
        directory = source_root / directory_name
        if directory.exists():
            paths.extend(path for path in directory.glob("*.md") if path.is_file())
    return sorted(paths, key=lambda path: path.as_posix().casefold())


def _select_paths(vault_root: Path, scope: ScanScope, all_paths: list[Path]) -> list[Path]:
    if scope.mode in {"all", "changed"}:
        return all_paths
    if scope.mode == "papers":
        return [path for path in all_paths if path.parent.name.casefold() == "papers"]
    if scope.mode == "web":
        return [path for path in all_paths if path.parent.name.casefold() == "web"]

    requested = Path(scope.source or "")
    if requested.is_absolute() or ".." in requested.parts:
        raise AIWikiError("--source must name a Markdown file inside Sources/Papers or Sources/Web")
    normalized = requested.as_posix().casefold()
    matches = []
    for path in all_paths:
        relative_to_sources = path.relative_to(
            vault_root / SOURCE_ROOT_RELATIVE_PATH
        ).as_posix()
        if normalized in {path.name.casefold(), relative_to_sources.casefold()}:
            matches.append(path)
    if not matches:
        raise AIWikiError(f"source not found in Papers or Web: {scope.source}")
    if len(matches) > 1:
        raise AIWikiError(
            f"source filename is ambiguous; use Papers/ or Web/ prefix: {scope.source}"
        )
    return matches


def _load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "sources": {}}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AIWikiError(f"cannot read AI-Wiki state {path}: {exc}") from exc
    if not isinstance(value, dict) or value.get("version") != 1:
        raise AIWikiError("AI-Wiki state has an unsupported format")
    if not isinstance(value.get("sources"), dict):
        raise AIWikiError("AI-Wiki state is missing the sources mapping")
    return value


def _existing_index(
    output_root: Path,
    plan: ProcessingPlan,
) -> tuple[dict[str, ExistingConcept], dict[str, str], dict[str, str], dict[str, str]]:
    by_identity: dict[str, ExistingConcept] = {}
    filename_owners: dict[str, str] = {}
    protected_filenames: dict[str, str] = {}
    protected_identities: dict[str, str] = {}
    if not output_root.exists():
        return by_identity, filename_owners, protected_filenames, protected_identities

    for path in sorted(output_root.glob("*.md"), key=lambda item: item.name.casefold()):
        try:
            existing = load_existing_concept(path)
        except ProtectedNoteError as exc:
            protected_filenames[path.name.casefold()] = str(exc)
            protected_identities[concept_identity(path.stem)] = str(exc)
            continue
        identity = concept_identity(existing.concept.title)
        if identity in by_identity:
            plan.warnings.append(
                f"Ambiguous existing concept identity {identity!r}: "
                f"{by_identity[identity].path.name}, {path.name}"
            )
            protected_filenames[path.name.casefold()] = "duplicate existing concept identity"
            protected_filenames[by_identity[identity].path.name.casefold()] = (
                "duplicate existing concept identity"
            )
            by_identity.pop(identity, None)
            continue
        by_identity[identity] = existing
        filename_owners[path.name.casefold()] = identity
    return by_identity, filename_owners, protected_filenames, protected_identities


def _attach_provenance(concept: Concept, source_link: str, chunk_id: str) -> None:
    if source_link not in concept.sources:
        concept.sources.append(source_link)
    concept.evidence = [
        Evidence(
            claim=item.claim,
            source_excerpt=item.source_excerpt,
            source_link=source_link,
            chunk_id=chunk_id,
        )
        for item in concept.evidence
    ]


def _merge_contradiction(existing: Concept, incoming: Concept) -> None:
    for source in incoming.sources:
        if source not in existing.sources:
            existing.sources.append(source)
    for domain in incoming.domain:
        if domain not in existing.domain:
            existing.domain.append(domain)
    evidence_keys = {
        (item.claim.casefold(), item.source_excerpt.casefold(), item.source_link.casefold())
        for item in existing.evidence
    }
    for item in incoming.evidence:
        key = (item.claim.casefold(), item.source_excerpt.casefold(), item.source_link.casefold())
        if key not in evidence_keys:
            evidence_keys.add(key)
            existing.evidence.append(item)


def _assert_ai_wiki_path(path: Path, output_root: Path) -> None:
    resolved_root = output_root.resolve()
    resolved_path = path.resolve()
    try:
        resolved_path.relative_to(resolved_root)
    except ValueError as exc:
        raise ProtectedNoteError(f"refusing write outside AI-Wiki: {path}") from exc
    if resolved_path.parent != resolved_root or resolved_path.suffix.casefold() != ".md":
        raise ProtectedNoteError(f"invalid AI-Wiki target path: {path}")


def _diagnostic_response_text(value: str) -> str:
    redacted = THINK_BLOCK_PATTERN.sub("[thinking redacted]", value)
    unclosed_think = re.search(r"<think\b[^>]*>", redacted, re.IGNORECASE)
    if unclosed_think:
        redacted = redacted[: unclosed_think.start()] + "[thinking redacted]"
    if len(redacted) > MAX_DIAGNOSTIC_RESPONSE_CHARS:
        omitted = len(redacted) - MAX_DIAGNOSTIC_RESPONSE_CHARS
        redacted = (
            redacted[:MAX_DIAGNOSTIC_RESPONSE_CHARS]
            + f"\n[diagnostic truncated: {omitted} characters omitted]"
        )
    return redacted


def _write_parse_diagnostic(
    *,
    vault_root: Path,
    source_relative_path: str,
    chunk_id: str,
    model_name: str,
    parse_error: str,
    raw_response: str,
    repair_raw_response: str | None,
    repair_error: str | None,
) -> tuple[str | None, str | None]:
    timestamp = datetime.now(timezone.utc)
    filename = f"{timestamp.strftime('%Y%m%dT%H%M%S.%fZ')}_{chunk_id}.json"
    path = vault_root / DIAGNOSTICS_RELATIVE_PATH / filename
    payload: dict[str, Any] = {
        "timestamp": timestamp.isoformat(),
        "source": source_relative_path,
        "chunk_id": chunk_id,
        "model": model_name,
        "parse_error": parse_error,
        "raw_structured_response": _diagnostic_response_text(raw_response),
        "repair": {
            "attempted": True,
            "succeeded": repair_error is None,
            "error": repair_error,
        },
    }
    if repair_raw_response is not None:
        payload["repair"]["raw_structured_response"] = _diagnostic_response_text(
            repair_raw_response
        )
    try:
        atomic_write_json(path, payload, overwrite=False)
    except OSError as exc:
        return None, f"could not write JSON parse diagnostic: {exc}"
    return path.relative_to(vault_root).as_posix(), None


def process_ai_wiki(
    *,
    vault_root: Path,
    provider: LLMProvider,
    model_name: str,
    scope: ScanScope,
    write: bool = False,
    today: date | None = None,
    max_chunk_chars: int = DEFAULT_MAX_CHUNK_CHARS,
) -> ProcessingPlan:
    root = vault_root.resolve()
    output_root = (root / AI_WIKI_RELATIVE_PATH).resolve()
    state_path = root / STATE_RELATIVE_PATH
    state = _load_state(state_path)
    previous_sources: dict[str, Any] = state["sources"]
    all_paths = _source_paths(root)
    all_relative_paths = {path.resolve().relative_to(root).as_posix() for path in all_paths}
    selected_paths = _select_paths(root, scope, all_paths)
    plan = ProcessingPlan()
    plan.removed_sources = sorted(set(previous_sources) - all_relative_paths)
    for relative in plan.removed_sources:
        plan.warnings.append(
            f"Source removed since last processing; no AI-Wiki content was deleted: {relative}"
        )

    candidates: dict[str, Concept] = {}
    identity_sources: dict[str, set[str]] = {}
    stem_counts: dict[str, int] = {}
    for path in all_paths:
        key = path.stem.casefold()
        stem_counts[key] = stem_counts.get(key, 0) + 1

    for path in selected_paths:
        relative = path.resolve().relative_to(root).as_posix()
        if stem_counts[path.stem.casefold()] > 1:
            plan.skipped.append(
                f"{relative}: duplicate Source filename makes Wikilink provenance ambiguous"
            )
            continue
        try:
            source = load_source_note(path, root)
        except SourceValidationError as exc:
            plan.skipped.append(f"{relative}: {exc}")
            continue

        previous = previous_sources.get(source.relative_path)
        if isinstance(previous, dict) and previous.get("sha256") == source.content_hash:
            plan.skipped.append(f"{source.relative_path}: unchanged")
            continue

        chunks = chunk_source(source, max_chars=max_chunk_chars)
        plan.stats.source_characters += len(source.content)
        plan.stats.chunk_count += len(chunks)
        plan.stats.chunk_characters += sum(len(chunk.text) for chunk in chunks)
        plan.stats.maximum_chunk_size = max(
            plan.stats.maximum_chunk_size,
            *(len(chunk.text) for chunk in chunks),
        )
        local_candidates: dict[str, Concept] = {}
        source_failed = False
        for chunk in chunks:
            system, prompt = build_extraction_prompt(chunk)
            try:
                plan.stats.llm_calls += 1
                response = provider.generate(
                    GenerateRequest(
                        prompt=prompt,
                        model=model_name,
                        system=system,
                        temperature=0.0,
                        max_output_tokens=AI_WIKI_MAX_OUTPUT_TOKENS,
                        response_format=CONCEPT_EXTRACTION_SCHEMA,
                        think=False,
                    )
                )
                if response.done_reason == "length":
                    raise StructuredOutputError(
                        "Local LLM output reached the 1024-token limit; "
                        "syntax repair was not attempted because content was truncated"
                    )
                try:
                    extracted = parse_concept_response(response.text)
                except MalformedJSONError as parse_exc:
                    plan.stats.json_repairs += 1
                    repair_system, repair_prompt = build_json_repair_prompt(response.text)
                    repair_raw_response: str | None = None
                    repair_error: str | None = None
                    try:
                        plan.stats.llm_calls += 1
                        repair_response = provider.generate(
                            GenerateRequest(
                                prompt=repair_prompt,
                                model=model_name,
                                system=repair_system,
                                temperature=0.0,
                                max_output_tokens=AI_WIKI_MAX_OUTPUT_TOKENS,
                                response_format=CONCEPT_EXTRACTION_SCHEMA,
                                think=False,
                            )
                        )
                        if repair_response.done_reason == "length":
                            raise StructuredOutputError(
                                "JSON repair output reached the 1024-token limit and was truncated"
                            )
                        repair_raw_response = repair_response.text
                        extracted = parse_concept_response(repair_raw_response)
                    except Exception as repair_exc:
                        if isinstance(repair_exc, ProviderTimeoutError):
                            plan.stats.timeout_failures += 1
                        repair_error = f"{type(repair_exc).__name__}: {repair_exc}"
                        diagnostic_path, diagnostic_error = _write_parse_diagnostic(
                            vault_root=root,
                            source_relative_path=source.relative_path,
                            chunk_id=chunk.identifier,
                            model_name=model_name,
                            parse_error=str(parse_exc),
                            raw_response=response.text,
                            repair_raw_response=repair_raw_response,
                            repair_error=repair_error,
                        )
                        if diagnostic_path:
                            plan.warnings.append(
                                f"JSON parse diagnostic: {diagnostic_path}"
                            )
                        if diagnostic_error:
                            plan.warnings.append(diagnostic_error)
                        raise StructuredOutputError(
                            f"JSON syntax repair failed after one attempt: {repair_error}"
                        ) from repair_exc

                    diagnostic_path, diagnostic_error = _write_parse_diagnostic(
                        vault_root=root,
                        source_relative_path=source.relative_path,
                        chunk_id=chunk.identifier,
                        model_name=model_name,
                        parse_error=str(parse_exc),
                        raw_response=response.text,
                        repair_raw_response=repair_raw_response,
                        repair_error=None,
                    )
                    if diagnostic_path:
                        plan.warnings.append(
                            f"JSON syntax repaired once; diagnostic: {diagnostic_path}"
                        )
                    if diagnostic_error:
                        plan.warnings.append(diagnostic_error)
            except Exception as exc:
                if isinstance(exc, ProviderTimeoutError):
                    plan.stats.timeout_failures += 1
                plan.failures.append(
                    f"{source.relative_path} {chunk.identifier}: {type(exc).__name__}: {exc}"
                )
                source_failed = True
                break
            if not extracted:
                plan.warnings.append(
                    f"{source.relative_path} {chunk.identifier}: no concepts extracted"
                )
            for concept in extracted:
                exclusion_reason = concept_exclusion_reason(
                    concept.title,
                    source.metadata.get("title"),
                )
                if exclusion_reason:
                    plan.skipped.append(
                        f"{source.relative_path} {chunk.identifier}: "
                        f"concept candidate {concept.title!r} excluded because it "
                        f"{exclusion_reason}"
                    )
                    continue
                _attach_provenance(concept, source.link, chunk.identifier)
                identity = concept_identity(concept.title)
                if identity in local_candidates:
                    merge_concepts(local_candidates[identity], concept)
                else:
                    local_candidates[identity] = concept

        if source_failed:
            continue
        if len(local_candidates) > MAX_CONCEPTS_PER_SOURCE:
            plan.failures.append(
                f"{source.relative_path}: extracted {len(local_candidates)} concepts; "
                f"the conservative limit is {MAX_CONCEPTS_PER_SOURCE}"
            )
            continue

        plan.processed_sources.append(source.relative_path)
        for identity, concept in local_candidates.items():
            identity_sources.setdefault(identity, set()).add(source.relative_path)
            if identity in candidates:
                merge_concepts(candidates[identity], concept)
            else:
                candidates[identity] = concept
        plan.state_updates[source.relative_path] = {
            "sha256": source.content_hash,
            "chunks": [chunk.identifier for chunk in chunks],
            "concepts": sorted(local_candidates),
        }

    plan.relation_suggestions.extend(suggest_relations(candidates.values()))

    (
        existing_by_identity,
        filename_owners,
        protected_filenames,
        protected_identities,
    ) = _existing_index(output_root, plan)
    jobs: list[tuple[str, Concept, Path, ExistingConcept | None]] = []
    blocked_identities: set[str] = set()
    planned_filename_owners = dict(filename_owners)
    for identity, concept in sorted(candidates.items(), key=lambda item: item[0]):
        filename = concept_filename(concept.title)
        filename_key = filename.casefold()
        existing = existing_by_identity.get(identity)
        path = existing.path if existing else output_root / filename
        if identity in protected_identities:
            plan.warnings.append(
                f"Protected concept identity skipped for {concept.title!r}: "
                f"{protected_identities[identity]}"
            )
            blocked_identities.add(identity)
            continue
        if filename_key in protected_filenames:
            plan.warnings.append(
                f"Protected concept target skipped for {concept.title!r}: "
                f"{protected_filenames[filename_key]}"
            )
            blocked_identities.add(identity)
            continue
        owner = planned_filename_owners.get(path.name.casefold())
        if owner is not None and owner != identity:
            plan.warnings.append(
                f"Concept filename collision skipped: {concept.title!r} -> {path.name}"
            )
            blocked_identities.add(identity)
            continue
        planned_filename_owners[path.name.casefold()] = identity
        jobs.append((identity, concept, path, existing))

    for identity in blocked_identities:
        for source_relative in identity_sources.get(identity, set()):
            plan.state_updates.pop(source_relative, None)

    known_titles = {
        identity: existing.concept.title
        for identity, existing in existing_by_identity.items()
    }
    for identity, concept, _path, existing in jobs:
        known_titles[identity] = existing.concept.title if existing else concept.title

    today_string = (today or date.today()).isoformat()
    for identity, incoming, path, existing in jobs:
        _assert_ai_wiki_path(path, output_root)
        if existing is None:
            concept = copy.deepcopy(incoming)
            concept.sources.sort(key=str.casefold)
            concept.domain.sort(key=str.casefold)
            content = render_concept_note(
                concept,
                created=today_string,
                updated=today_string,
                provider_name=provider.name,
                model_name=model_name,
                known_titles=known_titles,
            )
            plan.changes.append(
                PlannedChange("create", concept.title, path, None, content)
            )
            continue

        relation = classify_relation(existing.concept, incoming)
        concept = copy.deepcopy(existing.concept)
        if relation == "contradicts":
            _merge_contradiction(concept, incoming)
            plan.warnings.append(
                f"Potential contradiction preserved without replacing existing text: {concept.title}"
            )
        else:
            merge_concepts(concept, incoming)
        concept.sources.sort(key=str.casefold)
        concept.domain.sort(key=str.casefold)
        existing_updated = str(existing.metadata.get("updated", existing.created))
        tentative = render_concept_note(
            concept,
            created=existing.created,
            updated=existing_updated,
            provider_name=provider.name,
            model_name=model_name,
            known_titles=known_titles,
            existing_metadata=existing.metadata,
        )
        if tentative == existing.original_text:
            plan.changes.append(
                PlannedChange("unchanged", concept.title, path, relation, None)
            )
        else:
            content = render_concept_note(
                concept,
                created=existing.created,
                updated=today_string,
                provider_name=provider.name,
                model_name=model_name,
                known_titles=known_titles,
                existing_metadata=existing.metadata,
            )
            plan.changes.append(
                PlannedChange("update", concept.title, path, relation, content)
            )

    if write:
        for change in plan.changed_notes:
            _assert_ai_wiki_path(change.path, output_root)
            if change.action == "update":
                load_existing_concept(change.path)
            atomic_write_text(
                change.path,
                change.content or "",
                overwrite=change.action == "update",
            )
        if plan.state_updates:
            next_state = copy.deepcopy(state)
            next_state["sources"].update(plan.state_updates)
            atomic_write_json(state_path, next_state, overwrite=True)

    return plan
