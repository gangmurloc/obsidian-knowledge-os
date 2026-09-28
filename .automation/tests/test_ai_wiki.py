from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch


AUTOMATION_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AUTOMATION_ROOT))

from knowledge_os.ai_wiki import (  # noqa: E402
    ScanScope,
    StructuredOutputError,
    process_ai_wiki,
)
from knowledge_os.ai_wiki.engine import AI_WIKI_MAX_OUTPUT_TOKENS  # noqa: E402
from knowledge_os.ai_wiki.curator import (  # noqa: E402
    CURATOR_SELECTION_SCHEMA,
    MAX_FINAL_CONCEPTS,
    detect_duplicate_risk_groups,
)
from knowledge_os.ai_wiki.ontology import concept_identity  # noqa: E402
from knowledge_os.ai_wiki.schema import (  # noqa: E402
    CONCEPT_EXTRACTION_SCHEMA,
    MAX_CONCEPTS_PER_CHUNK,
    build_extraction_prompt,
    parse_concept_response,
)
from knowledge_os.ai_wiki.source import (  # noqa: E402
    DEFAULT_MAX_CHUNK_CHARS,
    chunk_source,
    load_source_note,
)
from knowledge_os.llm import FakeLLMProvider, ProviderTimeoutError  # noqa: E402


def concept_value(
    title: str,
    *,
    definition: str | None = None,
    key_points: list[str] | None = None,
    role: str = "core_concept",
) -> dict:
    return {
        "title": title,
        "definition": definition or f"{title} definition",
        "core_idea": f"{title} core idea",
        "mechanism": f"{title} mechanism",
        "role": role,
        "key_points": key_points or [f"{title} key point"],
        "related_concepts": ["Future Concept"],
        "evidence": [
            {
                "claim": f"{title} claim",
                "source_excerpt": f"Evidence for {title}.",
            }
        ],
        "open_questions": [f"How should {title} be verified?"],
        "domain": ["Natural Language Processing"],
    }


def response(*concepts: dict) -> str:
    return json.dumps({"concepts": list(concepts)}, ensure_ascii=False)


def curator_response(*identities: str) -> str:
    return json.dumps(
        {
            "selected": [
                {"identity": identity, "reason": f"Core concept {index}"}
                for index, identity in enumerate(identities, start=1)
            ]
        },
        ensure_ascii=False,
    )


class AIWikiTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.vault = Path(self.temp_directory.name)
        self.papers = self.vault / "30_Resources" / "Sources" / "Papers"
        self.web = self.vault / "30_Resources" / "Sources" / "Web"
        self.ai_wiki = self.vault / "30_Resources" / "AI-Wiki"
        self.knowledge = self.vault / "30_Resources" / "Knowledge"
        for directory in (self.papers, self.web, self.ai_wiki, self.knowledge):
            directory.mkdir(parents=True)
        self.today = date(2026, 9, 26)

    def tearDown(self):
        self.temp_directory.cleanup()

    def _source(
        self,
        name: str = "source-one.md",
        *,
        body: str = "Self-attention relates positions within a sequence.",
        origin: str = "external",
        title: str = "Test Source",
        directory: Path | None = None,
    ) -> Path:
        path = (directory or self.papers) / name
        path.write_text(
            "---\n"
            "type: source\n"
            f"origin: {origin}\n"
            "source_type: pdf\n"
            "knowledge_status: raw\n"
            f"title: {json.dumps(title, ensure_ascii=False)}\n"
            "created: 2026-09-26\n"
            "updated: 2026-09-26\n"
            "source_file: _assets/PDF/test.pdf\n"
            "domain: []\n"
            "human_verified: false\n"
            "---\n\n"
            f"# {title}\n\n"
            "## Content\n\n"
            f"{body}\n\n"
            "## My Highlights\n\nUser-owned highlight must not enter extraction.\n",
            encoding="utf-8",
        )
        return path

    def _run(
        self,
        provider: FakeLLMProvider,
        *,
        scope: ScanScope | None = None,
        write: bool = False,
    ):
        return process_ai_wiki(
            vault_root=self.vault,
            provider=provider,
            model_name="fake-local:latest",
            scope=scope or ScanScope("all"),
            write=write,
            today=self.today,
        )

    def _diagnostics(self) -> list[Path]:
        directory = self.vault / ".automation" / "state" / "diagnostics"
        return sorted(directory.glob("*.json")) if directory.exists() else []

    def _missing_comma_response(self) -> tuple[str, str]:
        valid = response(concept_value("Transformer"))
        malformed = valid.replace('", "definition"', '" "definition"', 1)
        self.assertNotEqual(malformed, valid)
        return malformed, valid

    def _curator_case(self, curator_text: str, *, count: int = 13):
        body = "\n\n".join(
            f"Paragraph {index} " + (chr(65 + index % 26) * 3_400)
            for index in range(count)
        )
        source = self._source(body=body)
        source_before = source.read_bytes()
        extraction_responses = tuple(
            response(concept_value(f"Chunk {index} Concept"))
            for index in range(count)
        )
        provider = FakeLLMProvider(response_texts=extraction_responses + (curator_text,))
        return source, source_before, provider, self._run(provider)

    def test_01_one_source_creates_one_concept_plan(self):
        self._source()
        provider = FakeLLMProvider(response_text=response(concept_value("Self-Attention")))
        plan = self._run(provider)
        self.assertEqual([change.action for change in plan.changes], ["create"])
        self.assertFalse((self.ai_wiki / "Self-Attention.md").exists())
        self.assertFalse((self.vault / ".automation" / "state" / "ai_wiki.json").exists())

    def test_02_one_source_can_extract_multiple_concepts(self):
        self._source(body=("A" * 3_500) + "\n\n" + ("B" * 3_500))
        provider = FakeLLMProvider(
            response_texts=(
                response(concept_value("Transformer")),
                response(concept_value("Positional Encoding")),
            )
        )
        plan = self._run(provider)
        self.assertEqual(len(plan.changed_notes), 2)

    def test_03_unchanged_source_does_not_call_llm_or_rewrite(self):
        self._source()
        first = FakeLLMProvider(response_text=response(concept_value("Self-Attention")))
        self._run(first, write=True)
        note = self.ai_wiki / "Self-Attention.md"
        original = note.read_text(encoding="utf-8")

        second = FakeLLMProvider(response_texts=())
        plan = self._run(second)
        self.assertEqual(second.requests, [])
        self.assertEqual(plan.changes, [])
        self.assertEqual(note.read_text(encoding="utf-8"), original)

    def test_04_modified_source_produces_update_plan(self):
        source = self._source()
        first = FakeLLMProvider(
            response_text=response(
                concept_value("Self-Attention", key_points=["Original point"])
            )
        )
        self._run(first, write=True)
        source.write_text(source.read_text(encoding="utf-8") + "\nNew evidence.\n", encoding="utf-8")
        second = FakeLLMProvider(
            response_text=response(
                concept_value("Self-Attention", key_points=["Original point", "New point"])
            )
        )
        plan = self._run(second)
        self.assertEqual([change.action for change in plan.changes], ["update"])

    def test_05_two_sources_merge_same_concept_provenance(self):
        self._source("source-one.md")
        self._source("source-two.md", body="Additional source evidence.")
        provider = FakeLLMProvider(response_text=response(concept_value("Transformer")))
        plan = self._run(provider)
        self.assertEqual(len(plan.changed_notes), 1)
        content = plan.changed_notes[0].content or ""
        self.assertIn("[[source-one]]", content)
        self.assertIn("[[source-two]]", content)

    def test_06_existing_concept_is_extended(self):
        self._source("source-one.md")
        first = FakeLLMProvider(
            response_text=response(concept_value("Transformer", key_points=["Point one"]))
        )
        self._run(first, write=True)
        self._source("source-two.md", body="A second source extends the concept.")
        second = FakeLLMProvider(
            response_text=response(concept_value("Transformer", key_points=["Point two"]))
        )
        plan = self._run(second, scope=ScanScope("source", "source-two.md"))
        self.assertEqual(plan.changes[0].action, "update")
        self.assertEqual(plan.changes[0].relation, "extends")

    def test_07_malformed_llm_json_is_reported(self):
        self._source()
        plan = self._run(FakeLLMProvider(response_text="{not-json"))
        self.assertEqual(len(plan.failures), 1)
        self.assertEqual(plan.changes, [])

    def test_08_empty_llm_response_is_reported(self):
        self._source()
        plan = self._run(FakeLLMProvider(response_text=""))
        self.assertIn("empty response", plan.failures[0])

    def test_09_filename_collision_is_not_auto_merged(self):
        self._source(body=("A" * 3_500) + "\n\n" + ("B" * 3_500))
        provider = FakeLLMProvider(
            response_texts=(
                response(concept_value("A:B")),
                response(concept_value("AB")),
            )
        )
        plan = self._run(provider)
        self.assertEqual(len(plan.changed_notes), 1)
        self.assertTrue(any("filename collision" in warning for warning in plan.warnings))

    def test_10_self_attention_title_variants_share_identity(self):
        self._source(body=("A" * 3_500) + "\n\n" + ("B" * 3_500))
        provider = FakeLLMProvider(
            response_texts=(
                response(concept_value("Self Attention", key_points=["Point one"])),
                response(concept_value("Self-Attention", key_points=["Point two"])),
            )
        )
        plan = self._run(provider)
        self.assertEqual(len(plan.changed_notes), 1)
        self.assertIn("Point two", plan.changed_notes[0].content or "")

    def test_11_korean_concept_title_is_preserved(self):
        self._source()
        plan = self._run(
            FakeLLMProvider(response_text=response(concept_value("자기 주의 메커니즘")))
        )
        self.assertEqual(plan.changed_notes[0].path.name, "자기 주의 메커니즘.md")

    def test_12_malformed_source_yaml_is_skipped(self):
        path = self.papers / "broken.md"
        path.write_text("---\ndomain: [broken\n---\nBody", encoding="utf-8")
        provider = FakeLLMProvider(response_texts=())
        plan = self._run(provider)
        self.assertEqual(provider.requests, [])
        self.assertTrue(any("malformed YAML" in item for item in plan.skipped))

    def test_13_non_external_source_is_skipped(self):
        self._source(origin="me")
        provider = FakeLLMProvider(response_texts=())
        plan = self._run(provider)
        self.assertEqual(provider.requests, [])
        self.assertTrue(any("origin must be external" in item for item in plan.skipped))

    def test_14_writes_are_confined_to_ai_wiki(self):
        self._source()
        provider = FakeLLMProvider(response_text=response(concept_value("Transformer")))
        self._run(provider, write=True)
        self.assertTrue((self.ai_wiki / "Transformer.md").exists())
        self.assertEqual(list(self.knowledge.glob("*.md")), [])

    def test_15_origin_me_target_is_never_modified(self):
        self._source()
        target = self.ai_wiki / "Self-Attention.md"
        original = "---\ntype: concept\norigin: me\n---\n# Self-Attention\n"
        target.write_text(original, encoding="utf-8")
        provider = FakeLLMProvider(response_text=response(concept_value("Self Attention")))
        plan = self._run(provider, write=True)
        self.assertEqual(target.read_text(encoding="utf-8"), original)
        self.assertTrue(any("Protected concept identity" in item for item in plan.warnings))

    def test_16_understood_and_applied_targets_are_never_modified(self):
        for status in ("understood", "applied"):
            with self.subTest(status=status):
                with tempfile.TemporaryDirectory() as directory:
                    vault = Path(directory)
                    papers = vault / "30_Resources" / "Sources" / "Papers"
                    target_dir = vault / "30_Resources" / "AI-Wiki"
                    papers.mkdir(parents=True)
                    target_dir.mkdir(parents=True)
                    source = papers / "source.md"
                    source.write_text(self._source().read_text(encoding="utf-8"), encoding="utf-8")
                    target = target_dir / "Transformer.md"
                    original = (
                        "---\ntype: concept\norigin: ai\n"
                        f"knowledge_status: {status}\n"
                        "domain: []\ncreated: 2026-09-26\nupdated: 2026-09-26\n"
                        "sources: []\nhuman_verified: false\n---\n# Transformer\n"
                    )
                    target.write_text(original, encoding="utf-8")
                    provider = FakeLLMProvider(
                        response_text=response(concept_value("Transformer"))
                    )
                    plan = process_ai_wiki(
                        vault_root=vault,
                        provider=provider,
                        model_name="fake-local:latest",
                        scope=ScanScope("all"),
                        write=True,
                        today=self.today,
                    )
                    self.assertEqual(target.read_text(encoding="utf-8"), original)
                    self.assertTrue(plan.warnings)

    def test_17_invalid_filename_characters_are_removed(self):
        self._source()
        plan = self._run(
            FakeLLMProvider(response_text=response(concept_value('Bad:Title?*<>"')))
        )
        filename = plan.changed_notes[0].path.name
        self.assertEqual(filename, "BadTitle.md")

    def test_18_atomic_write_failure_leaves_no_partial_note_or_state(self):
        self._source()
        provider = FakeLLMProvider(response_text=response(concept_value("Transformer")))
        with patch("knowledge_os.io_utils.os.replace", side_effect=OSError("sync failure")):
            with self.assertRaises(OSError):
                self._run(provider, write=True)
        self.assertFalse((self.ai_wiki / "Transformer.md").exists())
        self.assertFalse((self.vault / ".automation" / "state" / "ai_wiki.json").exists())
        self.assertEqual(list(self.ai_wiki.glob("*.tmp")), [])

    def test_19_extraction_disables_thinking_and_uses_schema(self):
        self._source()
        provider = FakeLLMProvider(response_text=response(concept_value("Transformer")))
        self._run(provider)
        self.assertEqual(len(provider.requests), 1)
        self.assertIs(provider.requests[0].think, False)
        self.assertEqual(provider.requests[0].response_format, CONCEPT_EXTRACTION_SCHEMA)

    def test_20_removed_source_never_deletes_ai_wiki_note(self):
        state_path = self.vault / ".automation" / "state" / "ai_wiki.json"
        state_path.parent.mkdir(parents=True)
        state_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "sources": {
                        "30_Resources/Sources/Papers/deleted.md": {
                            "sha256": "old",
                            "chunks": ["chunk-old"],
                            "concepts": ["transformer"],
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        note = self.ai_wiki / "Transformer.md"
        note.write_text("existing AI-Wiki content", encoding="utf-8")
        plan = self._run(FakeLLMProvider(response_texts=()), write=True)
        self.assertEqual(
            plan.removed_sources,
            ["30_Resources/Sources/Papers/deleted.md"],
        )
        self.assertEqual(note.read_text(encoding="utf-8"), "existing AI-Wiki content")

    def test_21_unexpected_structured_field_is_rejected(self):
        self._source()
        value = concept_value("Transformer")
        value["untrusted_field"] = "must not pass"
        plan = self._run(FakeLLMProvider(response_text=response(value)))
        self.assertIn("unexpected fields", plan.failures[0])

    def test_22_missing_structured_field_is_rejected(self):
        self._source()
        value = concept_value("Transformer")
        value.pop("mechanism")
        plan = self._run(FakeLLMProvider(response_text=response(value)))
        self.assertIn("missing fields", plan.failures[0])

    def test_22a_invalid_concept_role_is_rejected(self):
        self._source()
        value = concept_value("Transformer")
        value["role"] = "implementation_detail"
        plan = self._run(FakeLLMProvider(response_text=response(value)))
        self.assertIn("role must be one of", plan.failures[0])

    def test_23_empty_concept_list_is_valid_and_reported(self):
        self._source()
        plan = self._run(FakeLLMProvider(response_text=response()))
        self.assertEqual(plan.failures, [])
        self.assertEqual(plan.changes, [])
        self.assertTrue(any("no concepts extracted" in item for item in plan.warnings))

    def test_24_llm_text_cannot_inject_html_or_wikilinks(self):
        self._source()
        value = concept_value("Transformer")
        value["definition"] = "<script>alert(1)</script> [[Untrusted Link]]"
        plan = self._run(FakeLLMProvider(response_text=response(value)))
        content = plan.changed_notes[0].content or ""
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", content)
        self.assertNotIn("<script>", content)
        self.assertNotIn("[[Untrusted Link]]", content)

    def test_25_duplicate_source_filenames_are_skipped_as_ambiguous(self):
        self._source("duplicate.md", directory=self.papers)
        self._source("duplicate.md", directory=self.web)
        provider = FakeLLMProvider(response_texts=())
        plan = self._run(provider)
        self.assertEqual(provider.requests, [])
        self.assertEqual(len(plan.skipped), 2)
        self.assertTrue(all("provenance ambiguous" in item for item in plan.skipped))

    def test_26_valid_json_does_not_call_repair_or_write_diagnostic(self):
        self._source()
        provider = FakeLLMProvider(response_text=response(concept_value("Transformer")))
        plan = self._run(provider)
        self.assertEqual(len(provider.requests), 1)
        self.assertEqual(len(plan.changed_notes), 1)
        self.assertEqual(self._diagnostics(), [])

    def test_27_missing_comma_is_repaired_once(self):
        self._source()
        malformed, valid = self._missing_comma_response()
        provider = FakeLLMProvider(response_texts=(malformed, valid))
        plan = self._run(provider)
        self.assertEqual(len(provider.requests), 2)
        self.assertEqual(len(plan.changed_notes), 1)
        self.assertIs(provider.requests[1].think, False)
        self.assertEqual(provider.requests[1].temperature, 0.0)
        self.assertEqual(provider.requests[1].response_format, CONCEPT_EXTRACTION_SCHEMA)
        self.assertEqual(len(self._diagnostics()), 1)
        self.assertEqual(plan.stats.llm_calls, 2)
        self.assertEqual(plan.stats.json_repairs, 1)
        self.assertEqual(plan.stats.timeout_failures, 0)

    def test_28_broken_quote_escaping_is_repaired_once(self):
        self._source()
        valid = response(concept_value("Transformer"))
        malformed = valid.replace(
            "Transformer definition",
            'Transformer "definition"',
            1,
        )
        provider = FakeLLMProvider(response_texts=(malformed, valid))
        plan = self._run(provider)
        self.assertEqual(len(provider.requests), 2)
        self.assertEqual(len(plan.changed_notes), 1)

    def test_29_repair_failure_becomes_final_chunk_failure(self):
        self._source()
        malformed, _valid = self._missing_comma_response()
        provider = FakeLLMProvider(response_texts=(malformed, malformed))
        plan = self._run(provider)
        self.assertEqual(len(provider.requests), 2)
        self.assertEqual(plan.changes, [])
        self.assertIn("repair failed after one attempt", plan.failures[0])
        self.assertEqual(len(self._diagnostics()), 1)

    def test_30_schema_invalid_repair_is_rejected(self):
        self._source()
        malformed, _valid = self._missing_comma_response()
        schema_invalid = json.dumps({"concepts": [{"title": "Transformer"}]})
        provider = FakeLLMProvider(response_texts=(malformed, schema_invalid))
        plan = self._run(provider)
        self.assertEqual(len(provider.requests), 2)
        self.assertEqual(plan.changes, [])
        self.assertIn("missing fields", plan.failures[0])

    def test_31_repair_is_never_attempted_more_than_once(self):
        self._source()
        malformed, valid = self._missing_comma_response()
        provider = FakeLLMProvider(response_texts=(malformed, malformed, valid))
        plan = self._run(provider)
        self.assertEqual(len(provider.requests), 2)
        self.assertTrue(plan.failures)

    def test_32_diagnostic_is_created_only_for_json_parse_failure(self):
        self._source()
        schema_invalid = json.dumps({"concepts": [{"title": "Transformer"}]})
        provider = FakeLLMProvider(response_text=schema_invalid)
        plan = self._run(provider)
        self.assertEqual(len(provider.requests), 1)
        self.assertTrue(plan.failures)
        self.assertEqual(self._diagnostics(), [])

    def test_33_diagnostic_does_not_modify_source_or_knowledge(self):
        source = self._source()
        source_before = source.read_text(encoding="utf-8")
        knowledge = self.knowledge / "Human Note.md"
        knowledge.write_text("---\norigin: me\n---\nHuman content.\n", encoding="utf-8")
        knowledge_before = knowledge.read_text(encoding="utf-8")
        malformed, valid = self._missing_comma_response()
        provider = FakeLLMProvider(response_texts=(malformed, valid))
        self._run(provider)

        diagnostics = self._diagnostics()
        self.assertEqual(len(diagnostics), 1)
        diagnostic = json.loads(diagnostics[0].read_text(encoding="utf-8"))
        self.assertEqual(
            diagnostic["source"],
            "30_Resources/Sources/Papers/source-one.md",
        )
        self.assertEqual(diagnostic["model"], "fake-local:latest")
        self.assertIn("malformed JSON", diagnostic["parse_error"])
        self.assertEqual(diagnostic["raw_structured_response"], malformed)
        self.assertNotIn(str(self.vault), diagnostics[0].read_text(encoding="utf-8"))
        self.assertEqual(source.read_text(encoding="utf-8"), source_before)
        self.assertEqual(knowledge.read_text(encoding="utf-8"), knowledge_before)
        self.assertEqual(list(self.ai_wiki.glob("*.md")), [])

    def test_34_diagnostic_redacts_embedded_thinking_block(self):
        self._source()
        malformed, valid = self._missing_comma_response()
        with_thinking = f"<think>private reasoning trace</think>{malformed}"
        provider = FakeLLMProvider(response_texts=(with_thinking, valid))
        self._run(provider)
        diagnostic = self._diagnostics()[0].read_text(encoding="utf-8")
        self.assertIn("[thinking redacted]", diagnostic)
        self.assertNotIn("private reasoning trace", diagnostic)

    def test_35_long_source_uses_four_thousand_character_chunks(self):
        body = "\n\n".join(
            f"Paragraph {index} " + (str(index) * 1_480)
            for index in range(1, 10)
        )
        path = self._source(body=body)
        source = load_source_note(path, self.vault)
        chunks = chunk_source(source)
        self.assertGreater(len(source.content), 12_000)
        self.assertGreaterEqual(len(chunks), 3)
        self.assertTrue(all(len(chunk.text) <= DEFAULT_MAX_CHUNK_CHARS for chunk in chunks))

    def test_36_chunking_prefers_complete_paragraph_boundaries(self):
        paragraphs = [character * 1_800 for character in "ABCD"]
        path = self._source(body="\n\n".join(paragraphs))
        source = load_source_note(path, self.vault)
        chunks = chunk_source(source)
        self.assertEqual(chunks[0].text, "\n\n".join(paragraphs[:2]))
        self.assertTrue(all(paragraph in chunks[0].text for paragraph in paragraphs[:2]))
        self.assertNotIn(paragraphs[2], chunks[0].text)

    def test_37_more_than_one_concept_in_one_chunk_is_rejected(self):
        self._source()
        values = [concept_value(f"Concept {index}") for index in range(2)]
        provider = FakeLLMProvider(response_text=response(*values))
        plan = self._run(provider)
        self.assertEqual(MAX_CONCEPTS_PER_CHUNK, 1)
        self.assertEqual(len(provider.requests), 1)
        self.assertIn("exceeds 1 items per chunk", plan.failures[0])

    def test_38_eighteen_candidates_are_curated_to_at_most_twelve(self):
        identities = [concept_identity(f"Chunk {index} Concept") for index in range(12)]
        knowledge = self.knowledge / "Human Note.md"
        knowledge.write_text("Human-owned content.\n", encoding="utf-8")
        knowledge_before = knowledge.read_bytes()
        source, source_before, provider, plan = self._curator_case(
            curator_response(*identities),
            count=18,
        )

        self.assertEqual(MAX_FINAL_CONCEPTS, 12)
        self.assertEqual(len(provider.requests), 19)
        self.assertEqual(plan.stats.curator_calls, 1)
        self.assertEqual(len(plan.candidate_concepts), 18)
        self.assertEqual(len(plan.selected_concepts), 12)
        self.assertEqual(len(plan.dropped_concepts), 6)
        self.assertEqual(len(plan.changed_notes), 12)
        self.assertEqual(plan.failures, [])
        curator_request = provider.requests[-1]
        self.assertEqual(curator_request.response_format, CURATOR_SELECTION_SCHEMA)
        self.assertEqual(curator_request.temperature, 0.0)
        self.assertIs(curator_request.think, False)
        self.assertNotIn("Paragraph 0", curator_request.prompt)
        self.assertIn("supporting_chunk_ids", curator_request.prompt)
        self.assertIn("chunk-0001", plan.changed_notes[0].content or "")
        self.assertEqual(source.read_bytes(), source_before)
        self.assertEqual(knowledge.read_bytes(), knowledge_before)
        self.assertEqual(list(self.ai_wiki.glob("*.md")), [])

    def test_39_array_field_upper_bounds_are_enforced(self):
        cases = {
            "key_points": ["point"] * 6,
            "related_concepts": [f"Related {index}" for index in range(6)],
            "evidence": [
                {"claim": f"claim {index}", "source_excerpt": f"excerpt {index}"}
                for index in range(4)
            ],
            "open_questions": [f"question {index}" for index in range(4)],
            "domain": [f"domain-{index}" for index in range(4)],
        }
        for field, oversized in cases.items():
            with self.subTest(field=field):
                value = concept_value("Transformer")
                value[field] = oversized
                with self.assertRaises(StructuredOutputError):
                    parse_concept_response(response(value))

    def test_40_processing_statistics_reflect_chunk_workload(self):
        body = "\n\n".join(character * 4_000 for character in "AB")
        self._source(body=body)
        provider = FakeLLMProvider(response_text=response(concept_value("Transformer")))
        plan = self._run(provider)
        self.assertEqual(plan.stats.source_characters, len(body))
        self.assertEqual(plan.stats.chunk_count, 2)
        self.assertLessEqual(plan.stats.maximum_chunk_size, DEFAULT_MAX_CHUNK_CHARS)
        self.assertEqual(plan.stats.llm_calls, 2)
        self.assertEqual(plan.stats.json_repairs, 0)
        self.assertEqual(plan.stats.curator_calls, 0)

    def test_41_timeout_failure_is_counted_without_retry(self):
        self._source()
        provider = FakeLLMProvider()
        with patch.object(
            provider,
            "generate",
            side_effect=ProviderTimeoutError("timed out after 180s"),
        ) as generate:
            plan = self._run(provider)
        self.assertEqual(generate.call_count, 1)
        self.assertEqual(plan.stats.llm_calls, 1)
        self.assertEqual(plan.stats.timeout_failures, 1)
        self.assertEqual(plan.stats.json_repairs, 0)
        self.assertIn("ProviderTimeoutError", plan.failures[0])

    def test_42_extraction_and_repair_use_bounded_output_budget(self):
        self._source()
        malformed, valid = self._missing_comma_response()
        provider = FakeLLMProvider(response_texts=(malformed, valid))
        plan = self._run(provider)
        self.assertFalse(plan.failures)
        self.assertEqual(len(provider.requests), 2)
        self.assertTrue(
            all(
                request.max_output_tokens == AI_WIKI_MAX_OUTPUT_TOKENS
                for request in provider.requests
            )
        )

    def test_43_length_truncation_does_not_attempt_json_repair(self):
        self._source()
        provider = FakeLLMProvider(
            response_text='{"concepts":[{"title":"truncated',
            done_reason="length",
        )
        plan = self._run(provider)
        self.assertEqual(len(provider.requests), 1)
        self.assertEqual(plan.stats.json_repairs, 0)
        self.assertIn("content was truncated", plan.failures[0])
        self.assertEqual(self._diagnostics(), [])

    def test_44_extraction_prompt_interpolates_source_and_schema(self):
        marker = "UNIQUE_SOURCE_MARKER_7821"
        path = self._source(body=marker)
        source = load_source_note(path, self.vault)
        chunk = chunk_source(source)[0]
        _system, prompt = build_extraction_prompt(chunk)
        self.assertIn(marker, prompt)
        self.assertIn('"maxItems":1', prompt)
        self.assertIn("explicitly named mechanism", prompt)
        self.assertIn("source-specific method/system entity", prompt)
        self.assertIn("core_concept, mechanism, component", prompt)
        self.assertNotIn("Note Construction", prompt)
        self.assertNotIn("{chunk.text}", prompt)
        self.assertNotIn("{json.dumps", prompt)

    def test_45_source_title_exact_match_is_excluded(self):
        self._source(title="Attention Is All You Need")
        plan = self._run(
            FakeLLMProvider(
                response_text=response(concept_value("Attention Is All You Need"))
            )
        )
        self.assertEqual(plan.changes, [])
        self.assertTrue(any("matches the Source title" in item for item in plan.skipped))

    def test_46_source_title_case_variation_is_excluded(self):
        self._source(title="Attention Is All You Need")
        plan = self._run(
            FakeLLMProvider(
                response_text=response(concept_value("attention is all you need"))
            )
        )
        self.assertEqual(plan.changes, [])

    def test_47_source_title_punctuation_variation_is_excluded(self):
        self._source(title="Attention Is All You Need")
        plan = self._run(
            FakeLLMProvider(
                response_text=response(concept_value("The Attention-Is-All-You-Need"))
            )
        )
        self.assertEqual(plan.changes, [])

    def test_48_source_title_substring_does_not_exclude_concept(self):
        self._source(title="Attention Is All You Need")
        plan = self._run(
            FakeLLMProvider(response_text=response(concept_value("Self-Attention")))
        )
        self.assertEqual([change.title for change in plan.changed_notes], ["Self-Attention"])

    def test_49_leading_article_variants_merge_to_canonical_title(self):
        self._source(body=("A" * 3_500) + "\n\n" + ("B" * 3_500))
        provider = FakeLLMProvider(
            response_texts=(
                response(concept_value("The Transformer Architecture")),
                response(concept_value("Transformer Architecture")),
            )
        )
        plan = self._run(provider)
        self.assertEqual(len(plan.changed_notes), 1)
        change = plan.changed_notes[0]
        self.assertEqual(change.title, "Transformer Architecture")
        self.assertEqual(change.path.name, "Transformer Architecture.md")
        self.assertIn("chunk-0001", change.content or "")
        self.assertIn("chunk-0002", change.content or "")

    def test_50_self_attention_variants_merge_to_hyphenated_canonical_title(self):
        self._source(body=("A" * 3_500) + "\n\n" + ("B" * 3_500))
        provider = FakeLLMProvider(
            response_texts=(
                response(concept_value("Self Attention")),
                response(concept_value("self-attention")),
            )
        )
        plan = self._run(provider)
        self.assertEqual(len(plan.changed_notes), 1)
        self.assertEqual(plan.changed_notes[0].title, "Self-Attention")

    def test_51_semantic_overlap_is_not_automatically_merged(self):
        self._source(body=("A" * 3_500) + "\n\n" + ("B" * 3_500))
        provider = FakeLLMProvider(
            response_texts=(
                response(concept_value("Attention Mechanism")),
                response(concept_value("Self-Attention Mechanism")),
            )
        )
        plan = self._run(provider)
        self.assertEqual(len(plan.changed_notes), 2)
        self.assertEqual(len(plan.relation_suggestions), 1)
        suggestion = plan.relation_suggestions[0]
        self.assertEqual(suggestion.subject, "Self-Attention Mechanism")
        self.assertEqual(suggestion.relation, "narrower_than")
        self.assertEqual(suggestion.object, "Attention Mechanism")
        self.assertTrue(
            all("narrower_than" not in (change.content or "") for change in plan.changes)
        )

    def test_52_contextual_title_overlap_is_related_not_merged(self):
        self._source(body=("A" * 3_500) + "\n\n" + ("B" * 3_500))
        provider = FakeLLMProvider(
            response_texts=(
                response(concept_value("Neural Machine Translation")),
                response(
                    concept_value("Attention Mechanism in Neural Machine Translation")
                ),
            )
        )
        plan = self._run(provider)
        self.assertEqual(len(plan.changed_notes), 2)
        self.assertEqual(plan.relation_suggestions[0].relation, "related_to")

    def test_53_section_headings_are_excluded(self):
        for heading in ("Introduction", "Results", "Discussion", "Conclusion"):
            with self.subTest(heading=heading):
                self._source()
                plan = self._run(
                    FakeLLMProvider(response_text=response(concept_value(heading)))
                )
                self.assertEqual(plan.changes, [])
                self.assertTrue(any("structure heading" in item for item in plan.skipped))

    def test_54_numbered_table_and_figure_headings_are_excluded(self):
        for heading in ("Table 2 Results", "Figure 3", "Section 4 Methods"):
            with self.subTest(heading=heading):
                self._source()
                plan = self._run(
                    FakeLLMProvider(response_text=response(concept_value(heading)))
                )
                self.assertEqual(plan.changes, [])
        self._source()
        retained = self._run(
            FakeLLMProvider(response_text=response(concept_value("Table Lookup")))
        )
        self.assertEqual([change.title for change in retained.changed_notes], ["Table Lookup"])

    def test_55_korean_title_normalization_preserves_text_and_normalizes_spacing(self):
        self.assertEqual(concept_identity("자기 주의 메커니즘"), concept_identity("자기-주의  메커니즘"))
        self._source()
        plan = self._run(
            FakeLLMProvider(response_text=response(concept_value("자기 주의 메커니즘")))
        )
        self.assertEqual(plan.changed_notes[0].title, "자기 주의 메커니즘")

    def test_56_existing_ai_wiki_title_and_path_are_not_renamed(self):
        self._source()
        target = self.ai_wiki / "The Transformer Architecture.md"
        target.write_text(
            "---\n"
            "type: concept\n"
            "origin: ai\n"
            "knowledge_status: processed\n"
            "domain: []\n"
            "created: 2026-09-20\n"
            "updated: 2026-09-20\n"
            "sources: []\n"
            "human_verified: false\n"
            "---\n\n"
            "# The Transformer Architecture\n",
            encoding="utf-8",
        )
        plan = self._run(
            FakeLLMProvider(
                response_text=response(concept_value("Transformer Architecture"))
            ),
            write=True,
        )
        self.assertEqual(plan.changed_notes[0].path, target)
        self.assertIn("# The Transformer Architecture\n", target.read_text(encoding="utf-8"))
        self.assertFalse((self.ai_wiki / "Transformer Architecture.md").exists())

    def test_57_processing_report_reaches_plan_without_modifying_source(self):
        body = (
            "### Page 1\n\n#### Method\n\nNormal method prose.\n\n"
            "| Model | Score |\n| A | 0.9 | extra |\n\n"
            "### Page 2\n\n[Picture text]\nBROKENFigureOCRText 12 44\n"
            "Figure 1: A preserved caption.\n\n"
            "The attention equation is defined as:\n\n#### Results\n\nResults prose."
        )
        source = self._source(body=body)
        before = source.read_bytes()
        provider = FakeLLMProvider(response_text=response())
        plan = self._run(provider)

        self.assertEqual(source.read_bytes(), before)
        self.assertGreater(plan.stats.processing_characters, 0)
        self.assertGreater(plan.stats.included_blocks, 0)
        self.assertTrue(any("Method" in item for item in plan.included_sections))
        self.assertTrue(any("malformed Markdown table" in item for item in plan.excluded_tables))
        self.assertTrue(any("picture-text block" in item for item in plan.excluded_figure_text))
        self.assertTrue(any("missing formula" in item for item in plan.formula_warnings))
        prompt = provider.requests[0].prompt
        self.assertNotIn("| A | 0.9 | extra |", prompt)
        self.assertNotIn("BROKENFigureOCRText", prompt)
        self.assertIn("Figure 1: A preserved caption.", prompt)

    def test_58_curator_rejects_unknown_concept_identity(self):
        _source, _before, provider, plan = self._curator_case(
            curator_response("invented-concept")
        )
        self.assertEqual(len(provider.requests), 14)
        self.assertEqual(plan.stats.curator_calls, 1)
        self.assertIn("unknown concept identity", plan.failures[0])
        self.assertEqual(plan.changes, [])

    def test_59_curator_rejects_duplicate_selection(self):
        identity = concept_identity("Chunk 0 Concept")
        _source, _before, provider, plan = self._curator_case(
            curator_response(identity, identity)
        )
        self.assertEqual(len(provider.requests), 14)
        self.assertIn("duplicate concept identity", plan.failures[0])
        self.assertEqual(plan.changes, [])

    def test_60_curator_rejects_more_than_twelve_selections(self):
        identities = [concept_identity(f"Chunk {index} Concept") for index in range(13)]
        _source, _before, provider, plan = self._curator_case(
            curator_response(*identities)
        )
        self.assertEqual(len(provider.requests), 14)
        self.assertIn("between 1 and 12 concepts", plan.failures[0])
        self.assertEqual(plan.changes, [])

    def test_61_malformed_curator_response_fails_without_fallback(self):
        source, source_before, provider, plan = self._curator_case('{"selected": [')
        self.assertEqual(len(provider.requests), 14)
        self.assertEqual(plan.stats.curator_calls, 1)
        self.assertIn("MalformedJSONError", plan.failures[0])
        self.assertEqual(plan.selected_concepts, [])
        self.assertEqual(plan.changes, [])
        self.assertEqual(source.read_bytes(), source_before)
        self.assertEqual(list(self.ai_wiki.glob("*.md")), [])

    def test_62_curator_timeout_fails_without_fallback(self):
        count = 13
        body = "\n\n".join(
            f"Paragraph {index} " + (chr(65 + index) * 3_400)
            for index in range(count)
        )
        self._source(body=body)
        provider = FakeLLMProvider(
            response_texts=tuple(
                response(concept_value(f"Chunk {index} Concept"))
                for index in range(count)
            )
        )
        original_generate = provider.generate

        def generate_or_timeout(request):
            if len(provider.requests) == count:
                raise ProviderTimeoutError("curator timed out")
            return original_generate(request)

        with patch.object(provider, "generate", side_effect=generate_or_timeout):
            plan = self._run(provider)
        self.assertEqual(plan.stats.curator_calls, 1)
        self.assertEqual(plan.stats.timeout_failures, 1)
        self.assertIn("source-level curator failed", plan.failures[0])
        self.assertIn("ProviderTimeoutError", plan.failures[0])
        self.assertEqual(plan.changes, [])

    def test_63_wrapper_variants_form_duplicate_risk_group(self):
        titles = (
            "Agentic Memory Architecture",
            "A-MEM Agentic Memory Architecture",
            "A-MEM Agentic Memory Framework",
            "A-MEM Agentic Memory System",
        )
        concepts = {}
        for title in titles:
            concept = parse_concept_response(response(concept_value(title)))[0]
            concepts[concept_identity(concept.title)] = concept
        groups = detect_duplicate_risk_groups(
            concepts,
            source_title="A-MEM: Agentic Memory for LLM Agents",
        )
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].signature, "agentic memory")
        self.assertEqual(set(groups[0].identities), set(concepts))

    def test_64_distinct_concepts_never_form_duplicate_risk_group(self):
        titles = (
            "Agentic Memory",
            "Memory Evolution",
            "Attention",
            "Self-Attention",
            "Memory Retrieval",
            "Link Generation",
        )
        concepts = {}
        for title in titles:
            concept = parse_concept_response(response(concept_value(title)))[0]
            concepts[concept_identity(concept.title)] = concept
        groups = detect_duplicate_risk_groups(
            concepts,
            source_title="A-MEM: Agentic Memory for LLM Agents",
        )
        self.assertEqual(groups, [])

    def test_65_duplicate_risk_triggers_curator_below_twelve_candidates(self):
        titles = (
            "A-MEM Agentic Memory Architecture",
            "A-MEM Agentic Memory Framework",
            "A-MEM Agentic Memory System",
        )
        body = "\n\n".join(
            f"Mechanism section {index} " + (chr(65 + index) * 3_400)
            for index in range(len(titles))
        )
        source = self._source(
            body=body,
            title="A-MEM: Agentic Memory for LLM Agents",
        )
        source_before = source.read_bytes()
        selected_identity = concept_identity(titles[0])
        provider = FakeLLMProvider(
            response_texts=tuple(
                response(concept_value(title)) for title in titles
            )
            + (curator_response(selected_identity),)
        )
        plan = self._run(provider)

        self.assertEqual(len(provider.requests), 4)
        self.assertEqual(plan.stats.curator_calls, 1)
        self.assertEqual(len(plan.candidate_concepts), 3)
        self.assertEqual(len(plan.selected_concepts), 1)
        self.assertEqual(len(plan.dropped_concepts), 2)
        self.assertEqual(len(plan.duplicate_risk_groups), 1)
        self.assertIn("duplicate-risk", plan.curator_trigger_reason[0])
        self.assertEqual(len(plan.selected_representatives), 1)
        self.assertEqual(len(plan.dropped_aliases), 2)
        self.assertEqual([change.title for change in plan.changed_notes], [titles[0]])
        self.assertIn("chunk-0001", plan.changed_notes[0].content or "")
        self.assertEqual(source.read_bytes(), source_before)
        self.assertEqual(list(self.ai_wiki.glob("*.md")), [])

    def test_66_contextual_wrapper_pair_forms_duplicate_risk(self):
        concepts = {}
        for title in ("Note Construction", "Note Construction Mechanism"):
            concept = parse_concept_response(response(concept_value(title)))[0]
            concepts[concept_identity(concept.title)] = concept

        groups = detect_duplicate_risk_groups(
            concepts,
            source_title="Composable Memory Operations",
        )

        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].signature, "note construction")
        self.assertEqual(set(groups[0].identities), set(concepts))

    def test_67_source_title_aliases_form_duplicate_risk(self):
        concepts = {}
        titles = (
            "Agentic Memory Update Mechanism",
            "A-MEM Memory Update Mechanism",
        )
        for title in titles:
            concept = parse_concept_response(response(concept_value(title)))[0]
            concepts[concept_identity(concept.title)] = concept

        groups = detect_duplicate_risk_groups(
            concepts,
            source_title="A-MEM: Agentic Memory for LLM Agents",
        )

        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].signature, "memory update")
        self.assertEqual(set(groups[0].identities), set(concepts))

    def test_67a_single_token_base_with_contextual_wrapper_is_detected(self):
        concepts = {}
        for title in ("Retrieval", "Retrieval Method"):
            concept = parse_concept_response(response(concept_value(title)))[0]
            concepts[concept_identity(concept.title)] = concept

        groups = detect_duplicate_risk_groups(
            concepts,
            source_title="Efficient Retrieval Study",
        )

        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].signature, "retrieval")

    def test_68_distinct_memory_concepts_and_singleton_wrapper_are_unchanged(self):
        concepts = {}
        titles = (
            "Memory Evolution",
            "Agentic Memory",
            "Selective Top-k Retrieval Mechanism",
        )
        for title in titles:
            concept = parse_concept_response(response(concept_value(title)))[0]
            concepts[concept_identity(concept.title)] = concept

        groups = detect_duplicate_risk_groups(
            concepts,
            source_title="A-MEM: Agentic Memory for LLM Agents",
        )

        self.assertEqual(groups, [])

    def test_69_baseline_and_analysis_roles_are_excluded_from_final_concepts(self):
        cases = (
            ("MemoryBank", "baseline"),
            ("A-MEM Scaling Analysis", "analysis"),
        )
        for index, (title, role) in enumerate(cases):
            with self.subTest(role=role):
                source = self._source(
                    name=f"role-{index}.md",
                    title="A-MEM: Agentic Memory for LLM Agents",
                )
                source_before = source.read_bytes()
                plan = self._run(
                    FakeLLMProvider(
                        response_text=response(concept_value(title, role=role))
                    ),
                    scope=ScanScope("source", source.name),
                )

                self.assertEqual(len(plan.candidate_concepts), 1)
                self.assertEqual(plan.selected_concepts, [])
                self.assertEqual(plan.changes, [])
                self.assertIn(f"role={role}", plan.dropped_concepts[0])
                self.assertEqual(source.read_bytes(), source_before)
                self.assertEqual(list(self.ai_wiki.glob("*.md")), [])

    def test_70_dataset_source_contribution_role_is_retained(self):
        source = self._source(
            title="EvalSet: A Dataset for Robust Evaluation",
        )
        plan = self._run(
            FakeLLMProvider(
                response_text=response(concept_value("EvalSet", role="dataset"))
            ),
            scope=ScanScope("source", source.name),
        )

        self.assertEqual([change.title for change in plan.changed_notes], ["EvalSet"])
        self.assertIn("retained because its identity", plan.selected_concepts[0])


if __name__ == "__main__":
    unittest.main()
