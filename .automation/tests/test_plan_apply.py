from __future__ import annotations

import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch


AUTOMATION_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AUTOMATION_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from knowledge_os.ai_wiki.plan_file import _digest  # noqa: E402
from knowledge_os.cli import main  # noqa: E402
from knowledge_os.llm import FakeLLMProvider  # noqa: E402
from test_llm_unload import concept_value, response  # noqa: E402


FAKE_MODEL = "fake-local:latest"
SOURCE_ONE = "30_Resources/Sources/Papers/source-one.md"
NOTE = "30_Resources/AI-Wiki/Self-Attention.md"


class PlanApplyTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.vault = Path(self.temp_directory.name)
        self.papers = self.vault / "30_Resources" / "Sources" / "Papers"
        self.ai_wiki = self.vault / "30_Resources" / "AI-Wiki"
        self.knowledge = self.vault / "30_Resources" / "Knowledge"
        self.plans = self.vault / ".automation" / "state" / "plans"
        self.state_path = self.vault / ".automation" / "state" / "ai_wiki.json"
        for directory in (self.papers, self.ai_wiki, self.knowledge):
            directory.mkdir(parents=True)
        config = self.vault / ".automation" / "config" / "local_llm.json"
        config.parent.mkdir(parents=True)
        config.write_text(json.dumps({"provider": "ollama", "model": FAKE_MODEL}), encoding="utf-8")

    def tearDown(self):
        self.temp_directory.cleanup()

    def _source(
        self,
        name: str = "source-one.md",
        *,
        body: str = "Self-attention relates positions within a sequence.",
        title: str = "Test Source",
    ) -> Path:
        path = self.papers / name
        path.write_text(
            "---\n"
            "type: source\n"
            "origin: external\n"
            "source_type: pdf\n"
            "knowledge_status: raw\n"
            f"title: {json.dumps(title)}\n"
            "created: 2026-09-26\n"
            "updated: 2026-09-26\n"
            "source_file: _assets/PDF/test.pdf\n"
            "domain: []\n"
            "human_verified: false\n"
            "---\n\n"
            f"# {title}\n\n"
            "## Content\n\n"
            f"{body}\n",
            encoding="utf-8",
        )
        return path

    def _main(self, provider_patch, *argv: str) -> tuple[int, str]:
        output = StringIO()
        with (
            provider_patch,
            patch("knowledge_os.cli.logging.basicConfig"),
            redirect_stdout(output),
        ):
            code = main(["--vault", str(self.vault), "ai-wiki", *argv])
        return code, output.getvalue()

    def _scan(self, provider: FakeLLMProvider, *flags: str) -> tuple[int, str]:
        return self._main(
            patch("knowledge_os.cli.create_provider", return_value=provider),
            "scan",
            "--all",
            *flags,
        )

    def _apply(self, plan: Path, *flags: str) -> tuple[int, str]:
        return self._main(
            patch(
                "knowledge_os.cli.create_provider",
                side_effect=AssertionError("apply must not create an LLM provider"),
            ),
            "apply",
            "--plan",
            plan.relative_to(self.vault).as_posix(),
            *flags,
        )

    def _refused(self, plan: Path, *flags: str) -> str:
        with self.assertLogs(level="ERROR") as logs:
            code, _output = self._apply(plan, *flags)
        self.assertEqual(code, 5)
        return "\n".join(logs.output)

    def _plan_files(self) -> list[Path]:
        return sorted(self.plans.glob("*.json")) if self.plans.exists() else []

    def _saved_plan(self, provider: FakeLLMProvider | None = None) -> Path:
        provider = provider or FakeLLMProvider(
            response_text=response(concept_value("Self-Attention"))
        )
        code, _output = self._scan(provider, "--save-plan")
        self.assertEqual(code, 0)
        plans = self._plan_files()
        self.assertTrue(plans)
        return plans[-1]

    def _rewrite(self, plan: Path, **changes) -> None:
        payload = json.loads(plan.read_text(encoding="utf-8"))
        payload.update(changes)
        payload["digest"] = _digest(payload)
        plan.write_text(json.dumps(payload), encoding="utf-8")

    def test_save_plan_writes_a_plan_and_review_copy_but_no_notes(self):
        self._source()
        provider = FakeLLMProvider(response_text=response(concept_value("Self-Attention")))

        code, output = self._scan(provider, "--save-plan")

        self.assertEqual(code, 0)
        plan = self._plan_files()[0]
        relative = plan.relative_to(self.vault).as_posix()
        self.assertRegex(relative, r"^\.automation/state/plans/\d{8}T\d{6}Z_all\.json$")
        self.assertIn(f"plan_saved: {relative}\n", output)
        self.assertIn(f"plan_review: {relative[:-5]}.review.md\n", output)
        payload = json.loads(plan.read_text(encoding="utf-8"))
        self.assertEqual(payload["model"], FAKE_MODEL)
        self.assertEqual(payload["quality_gate_status"], "pass")
        self.assertEqual(list(payload["sources"]), [SOURCE_ONE])
        self.assertIsNone(payload["sources"][SOURCE_ONE]["previous_state"])
        self.assertEqual(
            [(item["action"], item["path"]) for item in payload["changes"]],
            [("create", NOTE)],
        )
        review = plan.with_suffix(".review.md").read_text(encoding="utf-8")
        self.assertIn("## create: Self-Attention", review)
        self.assertIn(payload["changes"][0]["content"].rstrip("\n"), review)
        self.assertEqual(list(self.ai_wiki.glob("*.md")), [])
        self.assertFalse(self.state_path.exists())

    def test_save_plan_cannot_be_combined_with_write(self):
        self._source()
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit) as raised:
            self._scan(FakeLLMProvider(), "--write", "--save-plan")
        self.assertEqual(raised.exception.code, 2)

    def test_plan_is_not_saved_for_a_failed_run(self):
        cases = (
            (
                6,
                "semantic quality gate failure",
                "NEXUS: Neural Exchange for Unified Search",
                FakeLLMProvider(response_text=response(concept_value("NEXUS", role="component"))),
            ),
            (
                5,
                "technical failure",
                "Test Source",
                FakeLLMProvider(response_texts=("{not-json", "{still-not-json")),
            ),
        )
        for expected_code, reason, title, provider in cases:
            with self.subTest(reason=reason):
                self._source(title=title)
                code, output = self._scan(provider, "--save-plan")
                self.assertEqual(code, expected_code)
                self.assertIn(f"plan_saved: (not saved because of {reason})", output)
                self.assertEqual(self._plan_files(), [])

    def test_apply_without_write_prints_the_notes_and_writes_nothing(self):
        self._source()
        plan = self._saved_plan()
        content = json.loads(plan.read_text(encoding="utf-8"))["changes"][0]["content"]

        code, output = self._apply(plan)

        self.assertEqual(code, 0)
        self.assertIn("mode: dry-run\n", output)
        self.assertIn(f"  - create: Self-Attention: {NOTE}\n", output)
        self.assertIn(f"----- create: {NOTE} -----\n{content.rstrip()}\n", output)
        self.assertIn("status: valid; nothing was written.", output)
        self.assertEqual(list(self.ai_wiki.glob("*.md")), [])
        self.assertFalse(self.state_path.exists())

    def test_apply_write_writes_exactly_the_saved_notes_and_state(self):
        self._source()
        plan = self._saved_plan()
        payload = json.loads(plan.read_text(encoding="utf-8"))

        code, output = self._apply(plan, "--write")

        self.assertEqual(code, 0)
        self.assertIn("status: applied; wrote 1 note(s)", output)
        self.assertEqual(
            (self.vault / NOTE).read_bytes(),
            payload["changes"][0]["content"].encode("utf-8"),
        )
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertEqual(state["sources"], payload["state_updates"])

        untouched = FakeLLMProvider(response_texts=())
        code, report = self._scan(untouched)
        self.assertEqual(code, 0)
        self.assertEqual(untouched.requests, [])
        self.assertIn(f"{SOURCE_ONE}: unchanged", report)

    def test_apply_refuses_when_the_source_changed(self):
        source = self._source()
        plan = self._saved_plan()
        source.write_text(source.read_text(encoding="utf-8") + "\nNew evidence.\n", encoding="utf-8")

        self.assertIn("Source changed since plan", self._refused(plan, "--write"))
        self.assertEqual(list(self.ai_wiki.glob("*.md")), [])
        self.assertFalse(self.state_path.exists())

    def test_apply_refuses_when_a_note_to_create_already_exists(self):
        self._source()
        plan = self._saved_plan()
        (self.vault / NOTE).write_text("Someone else's note.\n", encoding="utf-8")

        self.assertIn("note already exists", self._refused(plan, "--write"))
        self.assertEqual((self.vault / NOTE).read_text(encoding="utf-8"), "Someone else's note.\n")
        self.assertFalse(self.state_path.exists())

    def test_apply_refuses_a_plan_edited_after_saving(self):
        self._source()
        plan = self._saved_plan()
        payload = json.loads(plan.read_text(encoding="utf-8"))
        payload["changes"][0]["content"] += "\nHuman edit.\n"
        plan.write_text(json.dumps(payload), encoding="utf-8")

        self.assertIn("was modified after it was saved", self._refused(plan, "--write"))
        self.assertEqual(list(self.ai_wiki.glob("*.md")), [])

    def test_apply_refuses_a_target_outside_ai_wiki(self):
        self._source()
        plan = self._saved_plan()
        payload = json.loads(plan.read_text(encoding="utf-8"))
        for path in ("30_Resources/Knowledge/Stolen.md", "../outside.md", "30_Resources/AI-Wiki/sub/x.md"):
            with self.subTest(path=path):
                payload["changes"][0]["path"] = path
                self._rewrite(plan, changes=payload["changes"])
                self._refused(plan, "--write")
                self.assertEqual(list(self.knowledge.iterdir()), [])
                self.assertFalse(self.state_path.exists())

    def test_apply_refuses_when_processing_state_changed(self):
        self._source()
        plan = self._saved_plan()
        self.state_path.write_text(
            json.dumps({"version": 1, "sources": {SOURCE_ONE: {"sha256": "other"}}}),
            encoding="utf-8",
        )

        self.assertIn("processing state changed", self._refused(plan, "--write"))
        self.assertEqual(list(self.ai_wiki.glob("*.md")), [])

    def test_apply_refuses_a_plan_from_another_processing_view_version(self):
        self._source()
        plan = self._saved_plan()
        self._rewrite(plan, processing_view_version=5)

        self.assertIn("different processing view version", self._refused(plan))

    def test_apply_is_all_or_nothing(self):
        self._source(body=("A" * 3_500) + "\n\n" + ("B" * 3_500))
        plan = self._saved_plan(
            FakeLLMProvider(
                response_texts=(
                    response(concept_value("Transformer")),
                    response(concept_value("Positional Encoding")),
                )
            )
        )
        (self.ai_wiki / "Transformer.md").write_text("Blocking note.\n", encoding="utf-8")

        self._refused(plan, "--write")

        self.assertFalse((self.ai_wiki / "Positional Encoding.md").exists())
        self.assertFalse(self.state_path.exists())

    def test_applying_the_same_plan_twice_is_refused(self):
        self._source()
        plan = self._saved_plan()
        self.assertEqual(self._apply(plan, "--write")[0], 0)
        written = (self.vault / NOTE).read_bytes()

        self._refused(plan, "--write")

        self.assertEqual((self.vault / NOTE).read_bytes(), written)

    def test_update_plan_applies_only_to_the_note_it_was_computed_against(self):
        self._source()
        first = FakeLLMProvider(response_text=response(concept_value("Self-Attention")))
        self.assertEqual(self._scan(first, "--write")[0], 0)
        note = self.vault / NOTE
        original = note.read_text(encoding="utf-8")

        self._source("source-two.md", body="A second source supports the same concept.")
        plan = self._saved_plan(
            FakeLLMProvider(response_text=response(concept_value("Self-Attention")))
        )
        payload = json.loads(plan.read_text(encoding="utf-8"))
        self.assertEqual([item["action"] for item in payload["changes"]], ["update"])

        note.write_text(original.replace("Self-Attention key point", "Edited key point"), encoding="utf-8")
        self.assertIn("note changed since plan", self._refused(plan, "--write"))

        note.write_text(original, encoding="utf-8")
        self.assertEqual(self._apply(plan, "--write")[0], 0)
        self.assertEqual(note.read_bytes(), payload["changes"][0]["content"].encode("utf-8"))
        self.assertIn("[[source-two]]", note.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
