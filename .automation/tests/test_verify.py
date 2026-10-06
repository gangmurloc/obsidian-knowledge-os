from __future__ import annotations

import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date
from io import StringIO
from pathlib import Path
from unittest.mock import patch


AUTOMATION_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AUTOMATION_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from knowledge_os.ai_wiki import AIWikiError, ProtectedNoteError, ScanScope, process_ai_wiki  # noqa: E402
from knowledge_os.ai_wiki.source import parse_markdown_frontmatter  # noqa: E402
from knowledge_os.ai_wiki.verify import check_note  # noqa: E402
from knowledge_os.cli import main  # noqa: E402
from knowledge_os.llm import FakeLLMProvider  # noqa: E402
from test_method_coverage import concept, response  # noqa: E402


FAKE_MODEL = "fake-local:latest"
IN_SOURCE = "Self-attention relates positions within a sequence."
NOT_IN_SOURCE = "A sentence that is not in the source."
TODAY = date(2026, 10, 6)
RECORD = (
    "- Verification: reviewed by Claude Code (AI) on 2026-10-06; "
    "1 of 2 evidence excerpts found verbatim in the Source."
)


class VerifyTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.vault = Path(self.temp_directory.name)
        self.papers = self.vault / "30_Resources" / "Sources" / "Papers"
        self.ai_wiki = self.vault / "30_Resources" / "AI-Wiki"
        self.knowledge = self.vault / "30_Resources" / "Knowledge"
        for directory in (self.papers, self.ai_wiki, self.knowledge):
            directory.mkdir(parents=True)
        self.source = self._source()
        self._scan(excerpts=(IN_SOURCE.upper(), NOT_IN_SOURCE))
        self.note = self.ai_wiki / "Self-Attention.md"

    def tearDown(self):
        self.temp_directory.cleanup()

    def _source(self, body: str = IN_SOURCE) -> Path:
        path = self.papers / "source-one.md"
        path.write_text(
            "---\n"
            "type: source\n"
            "origin: external\n"
            "source_type: pdf\n"
            "knowledge_status: raw\n"
            'title: "Test Source"\n'
            "created: 2026-09-26\n"
            "updated: 2026-09-26\n"
            "source_file: _assets/PDF/test.pdf\n"
            "domain: []\n"
            "human_verified: false\n"
            "---\n\n"
            "# Test Source\n\n"
            "## Content\n\n"
            f"{body}\n",
            encoding="utf-8",
        )
        return path

    def _scan(self, *, excerpts: tuple[str, ...]):
        provider = FakeLLMProvider(
            response_text=response(concept("Self-Attention", role="core_concept", excerpts=excerpts))
        )
        return process_ai_wiki(
            vault_root=self.vault,
            provider=provider,
            model_name=FAKE_MODEL,
            scope=ScanScope("all"),
            write=True,
            today=TODAY,
        )

    def _mark(self, note: str = "Self-Attention.md", reviewer: str | None = "Claude Code"):
        return check_note(
            vault_root=self.vault,
            note=note,
            reviewer=reviewer,
            write=True,
            today=TODAY,
        )

    def _main(self, *argv: str) -> tuple[int, str]:
        output = StringIO()
        with patch("knowledge_os.cli.logging.basicConfig"), redirect_stdout(output):
            code = main(["--vault", str(self.vault), "ai-wiki", "verify", *argv])
        return code, output.getvalue()

    def test_scan_never_sets_the_flag(self):
        text = self.note.read_text(encoding="utf-8")
        self.assertIn("human_verified: false\n", text)
        self.assertNotIn("verified_by", text)

    def test_check_reports_evidence_without_changing_the_note(self):
        before = self.note.read_bytes()

        check = check_note(vault_root=self.vault, note="Self-Attention")

        self.assertEqual(check.status, "checked")
        self.assertEqual(check.relative_path, "30_Resources/AI-Wiki/Self-Attention.md")
        self.assertEqual(check.title, "Self-Attention")
        self.assertEqual(check.sources, ("[[source-one]]",))
        self.assertEqual((check.evidence_located, check.evidence_total), (1, 2))
        self.assertEqual(check.evidence_not_found, (2,))
        self.assertEqual(self.note.read_bytes(), before)

    def test_marking_changes_only_the_flag_and_the_review_record(self):
        before = self.note.read_text(encoding="utf-8").splitlines()

        check = self._mark()

        after_text = self.note.read_text(encoding="utf-8")
        after = after_text.splitlines()
        self.assertEqual(check.status, "marked")
        self.assertEqual(set(before) - set(after), {"human_verified: false"})
        self.assertEqual(
            set(after) - set(before),
            {"human_verified: true", "verified_by: ai", RECORD},
        )
        self.assertEqual(len(after), len(before) + 2)
        self.assertTrue(after_text.endswith(f"{RECORD}\n"))
        metadata, _body = parse_markdown_frontmatter(after_text)
        self.assertIs(metadata["human_verified"], True)
        self.assertEqual(metadata["verified_by"], "ai")
        self.assertEqual(metadata["origin"], "ai")

    def test_marking_requires_a_plain_reviewer_name(self):
        before = self.note.read_bytes()
        for reviewer in (None, "", "   ", "[[Someone]]", "line\nbreak", "x" * 81):
            with self.subTest(reviewer=reviewer):
                with self.assertRaisesRegex(AIWikiError, "reviewer"):
                    self._mark(reviewer=reviewer)
                self.assertEqual(self.note.read_bytes(), before)

    def test_already_verified_note_is_left_unchanged(self):
        self._mark()
        marked = self.note.read_bytes()

        check = self._mark(reviewer="Another Reviewer")

        self.assertEqual(check.status, "already verified")
        self.assertEqual(self.note.read_bytes(), marked)

    def test_only_ai_owned_notes_under_ai_wiki_can_be_marked(self):
        human_in_wiki = self.ai_wiki / "Human Draft.md"
        human_in_wiki.write_text(
            "---\ntype: concept\norigin: me\nknowledge_status: review\n"
            "human_verified: false\n---\n\n# Human Draft\n",
            encoding="utf-8",
        )
        knowledge = self.knowledge / "Human Note.md"
        knowledge.write_text(
            "---\ntype: concept\norigin: ai\nknowledge_status: processed\n"
            "human_verified: false\n---\n\n# Human Note\n",
            encoding="utf-8",
        )
        before = {path: path.read_bytes() for path in (human_in_wiki, knowledge)}

        for note in ("Human Draft.md", "../Knowledge/Human Note.md", "sub/Other.md"):
            with self.subTest(note=note):
                with self.assertRaises(ProtectedNoteError):
                    self._mark(note=note)
        for path, content in before.items():
            self.assertEqual(path.read_bytes(), content)

    def test_missing_note_or_missing_source_is_refused(self):
        with self.assertRaisesRegex(AIWikiError, "not found"):
            self._mark(note="No Such Note.md")
        before = self.note.read_bytes()
        self.source.rename(self.source.with_name("renamed.md"))

        with self.assertRaisesRegex(AIWikiError, "does not exist"):
            self._mark()
        self.assertEqual(self.note.read_bytes(), before)

    def test_marked_note_is_protected_from_later_scans(self):
        self._mark()
        marked = self.note.read_bytes()
        self.source.write_text(
            self.source.read_text(encoding="utf-8") + "\nNew evidence.\n",
            encoding="utf-8",
        )

        plan = self._scan(excerpts=(IN_SOURCE,))

        self.assertEqual(self.note.read_bytes(), marked)
        self.assertTrue(any("Protected concept" in warning for warning in plan.warnings))

    def test_cli_checks_by_default_and_marks_with_write_and_reviewer(self):
        before = self.note.read_bytes()

        code, output = self._main("--note", "Self-Attention.md")
        self.assertEqual(code, 0)
        self.assertIn("mode: dry-run\n", output)
        self.assertIn("  evidence_located: 1/2\n", output)
        self.assertIn("  evidence_not_found: 2\n", output)
        self.assertIn("  status: checked; nothing was written\n", output)
        self.assertEqual(self.note.read_bytes(), before)

        with self.assertLogs(level="ERROR"):
            code, _output = self._main("--note", "Self-Attention.md", "--write")
        self.assertEqual(code, 5)
        self.assertEqual(self.note.read_bytes(), before)

        code, output = self._main(
            "--note", "Self-Attention.md", "--write", "--reviewer", "Claude Code"
        )
        self.assertEqual(code, 0)
        self.assertIn(
            "  status: marked human_verified: true (verified_by: ai, reviewer: Claude Code)\n",
            output,
        )
        self.assertIn("human_verified: true\nverified_by: ai\n", self.note.read_text(encoding="utf-8"))

    def test_cli_marks_nothing_when_one_note_is_invalid(self):
        before = self.note.read_bytes()

        with self.assertLogs(level="ERROR"):
            code, _output = self._main(
                "--note", "Self-Attention.md",
                "--note", "No Such Note.md",
                "--write", "--reviewer", "Claude Code",
            )

        self.assertEqual(code, 5)
        self.assertEqual(self.note.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
