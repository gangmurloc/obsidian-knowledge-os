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

from knowledge_os.ai_wiki import ScanScope, process_ai_wiki  # noqa: E402
from knowledge_os.ai_wiki.schema import CONCEPT_EXTRACTION_SCHEMA  # noqa: E402
from knowledge_os.llm import FakeLLMProvider  # noqa: E402


def concept_value(
    title: str,
    *,
    definition: str | None = None,
    key_points: list[str] | None = None,
) -> dict:
    return {
        "title": title,
        "definition": definition or f"{title} definition",
        "core_idea": f"{title} core idea",
        "mechanism": f"{title} mechanism",
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
        directory: Path | None = None,
    ) -> Path:
        path = (directory or self.papers) / name
        path.write_text(
            "---\n"
            "type: source\n"
            f"origin: {origin}\n"
            "source_type: pdf\n"
            "knowledge_status: raw\n"
            "title: Test Source\n"
            "created: 2026-09-26\n"
            "updated: 2026-09-26\n"
            "source_file: _assets/PDF/test.pdf\n"
            "domain: []\n"
            "human_verified: false\n"
            "---\n\n"
            "# Test Source\n\n"
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

    def test_01_one_source_creates_one_concept_plan(self):
        self._source()
        provider = FakeLLMProvider(response_text=response(concept_value("Self-Attention")))
        plan = self._run(provider)
        self.assertEqual([change.action for change in plan.changes], ["create"])
        self.assertFalse((self.ai_wiki / "Self-Attention.md").exists())
        self.assertFalse((self.vault / ".automation" / "state" / "ai_wiki.json").exists())

    def test_02_one_source_can_extract_multiple_concepts(self):
        self._source()
        provider = FakeLLMProvider(
            response_text=response(
                concept_value("Transformer"),
                concept_value("Positional Encoding"),
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
        self._source()
        provider = FakeLLMProvider(
            response_text=response(concept_value("A:B"), concept_value("AB"))
        )
        plan = self._run(provider)
        self.assertEqual(len(plan.changed_notes), 1)
        self.assertTrue(any("filename collision" in warning for warning in plan.warnings))

    def test_10_self_attention_title_variants_share_identity(self):
        self._source()
        provider = FakeLLMProvider(
            response_text=response(
                concept_value("Self Attention", key_points=["Point one"]),
                concept_value("Self-Attention", key_points=["Point two"]),
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


if __name__ == "__main__":
    unittest.main()
