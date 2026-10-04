from __future__ import annotations

import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit


AUTOMATION_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AUTOMATION_ROOT))

from knowledge_os.ai_wiki import ScanScope, process_ai_wiki  # noqa: E402
from knowledge_os.cli import main  # noqa: E402
from knowledge_os.io_utils import atomic_write_json, atomic_write_text  # noqa: E402
from knowledge_os.llm import (  # noqa: E402
    FakeLLMProvider,
    OllamaProvider,
    ProviderRequestError,
    ProviderTimeoutError,
)


ENDPOINT = "http://localhost:11435"
MODEL = "lab-model:27b"
FAKE_MODEL = "fake-local:latest"
QUALITY_FAILURE_TITLE = "NEXUS: Neural Exchange for Unified Search"


def concept_value(title: str, *, role: str = "core_concept") -> dict:
    return {
        "title": title,
        "definition": f"{title} definition",
        "core_idea": f"{title} core idea",
        "mechanism": f"{title} mechanism",
        "role": role,
        "key_points": [f"{title} key point"],
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


class RoutingTransport:
    """Scripted stand-in for the Ollama HTTP transport; it never opens a socket."""

    def __init__(
        self,
        *,
        texts=(),
        models=(MODEL,),
        error: Exception | None = None,
        generate_error: Exception | None = None,
        unload_error: Exception | None = None,
        on_unload=None,
    ) -> None:
        self.texts = list(texts)
        self.models = models
        self.error = error
        self.generate_error = generate_error
        self.unload_error = unload_error
        self.on_unload = on_unload
        self.calls: list[dict] = []

    def __call__(self, method, url, payload, timeout):
        self.calls.append(
            {"method": method, "url": url, "payload": payload, "timeout": timeout}
        )
        if self.error is not None:
            raise self.error
        path = urlsplit(url).path
        if path == "/api/version":
            return {"version": "0.0.0-test"}
        if path == "/api/tags":
            return {"models": [{"name": name} for name in self.models]}
        if "prompt" not in payload:
            if self.on_unload is not None:
                self.on_unload()
            if self.unload_error is not None:
                raise self.unload_error
            return {
                "model": payload["model"],
                "response": "",
                "done": True,
                "done_reason": "unload",
            }
        if self.generate_error is not None:
            raise self.generate_error
        return {
            "model": payload["model"],
            "response": self.texts.pop(0),
            "done": True,
            "done_reason": "stop",
        }

    @property
    def paths(self) -> list[str]:
        return [urlsplit(call["url"]).path for call in self.calls]

    @property
    def generations(self) -> list[dict]:
        return [
            call
            for call in self.calls
            if call["payload"] is not None and "prompt" in call["payload"]
        ]

    @property
    def unloads(self) -> list[dict]:
        return [
            call
            for call in self.calls
            if call["payload"] is not None and "prompt" not in call["payload"]
        ]


class RunUnloadTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.vault = Path(self.temp_directory.name)
        self.papers = self.vault / "30_Resources" / "Sources" / "Papers"
        self.ai_wiki = self.vault / "30_Resources" / "AI-Wiki"
        self.state_path = self.vault / ".automation" / "state" / "ai_wiki.json"
        for directory in (self.papers, self.ai_wiki):
            directory.mkdir(parents=True)
        self._config()

    def tearDown(self):
        self.temp_directory.cleanup()

    def _config(self, value: dict | None = None, **overrides) -> None:
        if value is None:
            value = {
                "provider": "ollama",
                "base_url": ENDPOINT,
                "model": MODEL,
                "temperature": 0.0,
                "timeout": 300.0,
                "keep_alive": "2m",
                "unload_after_run": True,
            }
        value = {**value, **overrides}
        path = self.vault / ".automation" / "config" / "local_llm.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    def _source(self, *, title: str = "Test Source") -> Path:
        path = self.papers / "source-one.md"
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
            "Self-attention relates positions within a sequence.\n",
            encoding="utf-8",
        )
        return path

    def _main(self, transport: RoutingTransport, *argv: str) -> tuple[int, str]:
        output = StringIO()
        with (
            patch(
                "knowledge_os.cli.create_provider",
                side_effect=lambda config: OllamaProvider(config, transport=transport),
            ),
            patch("knowledge_os.cli.logging.basicConfig"),
            redirect_stdout(output),
        ):
            code = main(["--vault", str(self.vault), *argv])
        return code, output.getvalue()

    def _assert_single_unload_is_last(self, transport: RoutingTransport) -> None:
        self.assertEqual(
            [call["payload"] for call in transport.unloads],
            [{"model": MODEL, "keep_alive": 0}],
        )
        unload = transport.unloads[0]
        self.assertIs(transport.calls[-1], unload)
        self.assertEqual(unload["method"], "POST")
        self.assertEqual(unload["url"], f"{ENDPOINT}/api/generate")
        self.assertEqual(unload["timeout"], 10)

    def _assert_nothing_written(self) -> None:
        self.assertEqual(list(self.ai_wiki.glob("*.md")), [])
        self.assertFalse(self.state_path.exists())


class ScanUnloadTests(RunUnloadTestCase):
    def test_pass_path_unloads_once_and_reports_runtime_settings(self):
        self._source()
        transport = RoutingTransport(texts=[response(concept_value("Self-Attention"))])

        code, report = self._main(transport, "ai-wiki", "scan", "--all")

        self.assertEqual(code, 0)
        self.assertEqual(len(transport.generations), 1)
        self.assertEqual(transport.generations[0]["payload"]["keep_alive"], "2m")
        self._assert_single_unload_is_last(transport)
        self._assert_nothing_written()
        for expected in (
            "mode: dry-run",
            "llm:",
            f"  endpoint: {ENDPOINT}",
            f"  model: {MODEL}",
            "  keep_alive: 2m",
            "  unload_after_run: true",
            "  llm_calls: 1",
            "  unload_requests: 1",
        ):
            self.assertIn(expected, report)

    def test_quality_failure_exit_6_still_unloads_once(self):
        self._source(title=QUALITY_FAILURE_TITLE)
        for flags in ((), ("--write",)):
            with self.subTest(flags=flags):
                transport = RoutingTransport(
                    texts=[response(concept_value("NEXUS", role="component"))]
                )
                code, report = self._main(transport, "ai-wiki", "scan", "--all", *flags)
                self.assertEqual(code, 6)
                self.assertIn("  status: failed", report)
                self.assertIn("  llm_calls: 1", report)
                self.assertIn("  unload_requests: 1", report)
                self._assert_single_unload_is_last(transport)
                self._assert_nothing_written()

    def test_technical_failure_exit_5_still_unloads_once(self):
        self._source()
        for flags in ((), ("--write",)):
            with self.subTest(flags=flags):
                transport = RoutingTransport(texts=["{not-json", "{still-not-json"])
                code, report = self._main(transport, "ai-wiki", "scan", "--all", *flags)
                self.assertEqual(code, 5)
                self.assertEqual(len(transport.generations), 2)
                self.assertIn("  llm_calls: 2", report)
                self.assertIn("  unload_requests: 1", report)
                self._assert_single_unload_is_last(transport)
                self._assert_nothing_written()

    def test_timeout_failure_still_unloads_once_without_retry(self):
        self._source()
        transport = RoutingTransport(
            generate_error=ProviderTimeoutError("Ollama request timed out after 300s.")
        )

        code, report = self._main(transport, "ai-wiki", "scan", "--all")

        self.assertEqual(code, 5)
        self.assertEqual(len(transport.generations), 1)
        self.assertIn("  timeout_failures: 1", report)
        self._assert_single_unload_is_last(transport)

    def test_zero_llm_calls_send_no_unload(self):
        self._source()
        first = RoutingTransport(texts=[response(concept_value("Self-Attention"))])
        self.assertEqual(self._main(first, "ai-wiki", "scan", "--all", "--write")[0], 0)
        self.assertEqual(len(first.unloads), 1)

        second = RoutingTransport()
        code, report = self._main(second, "ai-wiki", "scan", "--all", "--write")

        self.assertEqual(code, 0)
        self.assertIn("source-one.md: unchanged", report)
        self.assertEqual(second.calls, [])
        self.assertIn("  llm_calls: 0", report)
        self.assertIn("  unload_requests: 0", report)

    def test_unload_after_run_false_sends_no_unload(self):
        self._source()
        self._config(unload_after_run=False)
        transport = RoutingTransport(texts=[response(concept_value("Self-Attention"))])

        code, report = self._main(transport, "ai-wiki", "scan", "--all")

        self.assertEqual(code, 0)
        self.assertEqual(len(transport.generations), 1)
        self.assertEqual(transport.generations[0]["payload"]["keep_alive"], "2m")
        self.assertEqual(transport.unloads, [])
        self.assertIn("  unload_after_run: false", report)
        self.assertIn("  unload_requests: 0", report)

    def test_config_without_new_keys_keeps_previous_request_shape(self):
        self._source()
        self._config(
            {
                "provider": "ollama",
                "base_url": "http://localhost:11434",
                "model": MODEL,
                "temperature": 0.0,
                "timeout": 180.0,
            }
        )
        transport = RoutingTransport(texts=[response(concept_value("Self-Attention"))])

        code, report = self._main(transport, "ai-wiki", "scan", "--all")

        self.assertEqual(code, 0)
        self.assertNotIn("keep_alive", transport.generations[0]["payload"])
        self.assertEqual(transport.unloads, [])
        self.assertIn("  keep_alive: (not set)", report)
        self.assertIn("  unload_after_run: false", report)

    def test_write_path_unloads_after_notes_and_state_exist(self):
        self._source()
        note = self.ai_wiki / "Self-Attention.md"
        seen: dict[str, bool] = {}
        transport = RoutingTransport(
            texts=[response(concept_value("Self-Attention"))],
            on_unload=lambda: seen.update(
                note=note.exists(),
                state=self.state_path.exists(),
            ),
        )

        code, report = self._main(transport, "ai-wiki", "scan", "--all", "--write")

        self.assertEqual(code, 0)
        self.assertIn("mode: write", report)
        self.assertEqual(seen, {"note": True, "state": True})
        self._assert_single_unload_is_last(transport)

    def test_unload_failure_is_one_warning_and_changes_nothing_else(self):
        self._source()
        transport = RoutingTransport(
            texts=[response(concept_value("Self-Attention"))],
            unload_error=ProviderRequestError("Ollama HTTP 500: unload\nrejected"),
        )

        code, report = self._main(transport, "ai-wiki", "scan", "--all", "--write")

        self.assertEqual(code, 0)
        self.assertTrue((self.ai_wiki / "Self-Attention.md").exists())
        self.assertTrue(self.state_path.exists())
        self.assertEqual(len(transport.unloads), 1)
        self.assertEqual(len(transport.generations), 1)
        warning_lines = [
            line for line in report.splitlines() if "ProviderRequestError" in line
        ]
        self.assertEqual(len(warning_lines), 1)
        self.assertIn("unload", warning_lines[0])
        self.assertTrue(warning_lines[0].startswith("  - "))
        self.assertIn("  unload_requests: 1", report)
        self.assertIn("failures:\n  (none)", report)

    def test_unload_failure_does_not_mask_quality_failure_exit_code(self):
        self._source(title=QUALITY_FAILURE_TITLE)
        transport = RoutingTransport(
            texts=[response(concept_value("NEXUS", role="component"))],
            unload_error=ProviderTimeoutError("Ollama request timed out after 10s."),
        )

        code, _report = self._main(transport, "ai-wiki", "scan", "--all", "--write")

        self.assertEqual(code, 6)
        self.assertEqual(len(transport.unloads), 1)
        self._assert_nothing_written()

    def test_connection_refused_fails_closed_without_fallback(self):
        self._source()
        transport = RoutingTransport(
            error=ProviderRequestError(
                "Cannot reach local Ollama server: [WinError 10061] connection refused"
            )
        )

        code, report = self._main(transport, "ai-wiki", "scan", "--all", "--write")

        self.assertEqual(code, 5)
        self.assertIn("  write_blocked: true", report)
        self._assert_nothing_written()
        self.assertEqual(
            {urlsplit(call["url"]).netloc for call in transport.calls},
            {"localhost:11435"},
        )
        self.assertEqual(transport.paths, ["/api/tags", "/api/generate"])
        self.assertEqual(transport.generations, [])
        self.assertEqual(len(transport.unloads), 1)

    def test_model_missing_on_server_fails_as_model_not_installed(self):
        self._source()
        transport = RoutingTransport(models=("other-model:4b",))

        code, report = self._main(transport, "ai-wiki", "scan", "--all", "--write")

        self.assertEqual(code, 5)
        self.assertIn("ModelNotInstalledError", report)
        self.assertEqual(transport.generations, [])
        self._assert_nothing_written()


class EngineUnloadTests(RunUnloadTestCase):
    def _run(self, provider: FakeLLMProvider, **kwargs):
        return process_ai_wiki(
            vault_root=self.vault,
            provider=provider,
            model_name=FAKE_MODEL,
            scope=ScanScope("all"),
            **kwargs,
        )

    def test_unload_is_not_counted_as_an_llm_call(self):
        self._source()
        provider = FakeLLMProvider(response_text=response(concept_value("Self-Attention")))

        plan = self._run(provider, unload_after_run=True)

        self.assertEqual(provider.unload_requests, [FAKE_MODEL])
        self.assertEqual(len(provider.requests), 1)
        self.assertEqual(plan.stats.llm_calls, 1)
        self.assertEqual(plan.stats.unload_requests, 1)

    def test_default_run_never_unloads(self):
        self._source()
        provider = FakeLLMProvider(response_text=response(concept_value("Self-Attention")))

        plan = self._run(provider)

        self.assertEqual(provider.unload_requests, [])
        self.assertEqual(plan.stats.unload_requests, 0)

    def test_write_order_is_notes_then_state_then_unload(self):
        self._source()
        provider = FakeLLMProvider(response_text=response(concept_value("Self-Attention")))
        events: list[str] = []

        def recording(name, function):
            def wrapper(*args, **kwargs):
                result = function(*args, **kwargs)
                events.append(name)
                return result

            return wrapper

        with (
            patch(
                "knowledge_os.ai_wiki.engine.atomic_write_text",
                side_effect=recording("note", atomic_write_text),
            ),
            patch(
                "knowledge_os.ai_wiki.engine.atomic_write_json",
                side_effect=recording("state", atomic_write_json),
            ),
            patch.object(
                provider,
                "unload",
                side_effect=lambda model: events.append(f"unload:{model}"),
            ),
        ):
            plan = self._run(provider, write=True, unload_after_run=True)

        self.assertEqual(events, ["note", "state", f"unload:{FAKE_MODEL}"])
        self.assertEqual(plan.stats.unload_requests, 1)

    def test_unload_still_runs_when_the_write_raises(self):
        self._source()
        provider = FakeLLMProvider(response_text=response(concept_value("Self-Attention")))

        with patch("knowledge_os.io_utils.os.replace", side_effect=OSError("sync failure")):
            with self.assertRaises(OSError):
                self._run(provider, write=True, unload_after_run=True)

        self.assertEqual(provider.unload_requests, [FAKE_MODEL])
        self._assert_nothing_written()

    def test_unload_failure_during_a_raising_run_is_logged_not_raised(self):
        self._source()
        provider = FakeLLMProvider(response_text=response(concept_value("Self-Attention")))

        with (
            patch("knowledge_os.io_utils.os.replace", side_effect=OSError("sync failure")),
            patch.object(
                provider,
                "unload",
                side_effect=ProviderRequestError("connection refused"),
            ) as unload,
            self.assertLogs("knowledge_os.ai_wiki.engine", level="WARNING") as logs,
        ):
            with self.assertRaises(OSError):
                self._run(provider, write=True, unload_after_run=True)

        self.assertEqual(unload.call_count, 1)
        self.assertEqual(len(logs.output), 1)
        self.assertIn("unload", logs.output[0])


class LLMTestUnloadTests(RunUnloadTestCase):
    def test_pass_path_unloads_once_and_reports_counts(self):
        transport = RoutingTransport(texts=["LOCAL_LLM_OK"])

        code, output = self._main(transport, "llm-test")

        self.assertEqual(code, 0)
        self.assertEqual(
            transport.paths,
            ["/api/version", "/api/tags", "/api/generate", "/api/generate"],
        )
        self.assertEqual(transport.generations[0]["payload"]["keep_alive"], "2m")
        self._assert_single_unload_is_last(transport)
        for expected in (
            f"endpoint: {ENDPOINT}",
            f"model: {MODEL}",
            "keep_alive: 2m",
            "unload_after_run: true",
            "llm_calls: 1",
            "unload_requests: 1",
            "LOCAL_LLM_OK",
        ):
            self.assertIn(expected, output)
        self.assertNotIn("warning:", output)

    def test_generation_failure_still_unloads_once(self):
        transport = RoutingTransport(
            generate_error=ProviderTimeoutError("Ollama request timed out after 300s.")
        )

        with self.assertLogs(level="ERROR") as logs:
            code, _output = self._main(transport, "llm-test")

        self.assertEqual(code, 4)
        self.assertEqual(len(transport.generations), 1)
        self._assert_single_unload_is_last(transport)
        self.assertEqual(len(logs.output), 1)

    def test_unreachable_server_makes_no_llm_call_and_no_unload(self):
        transport = RoutingTransport(
            error=ProviderRequestError(
                "Cannot reach local Ollama server: [WinError 10061] connection refused"
            )
        )

        with self.assertLogs(level="ERROR"):
            code, _output = self._main(transport, "llm-test")

        self.assertEqual(code, 4)
        self.assertEqual(transport.paths, ["/api/version"])
        self.assertEqual(
            {urlsplit(call["url"]).netloc for call in transport.calls},
            {"localhost:11435"},
        )

    def test_unload_after_run_false_sends_no_unload(self):
        self._config(unload_after_run=False)
        transport = RoutingTransport(texts=["LOCAL_LLM_OK"])

        code, output = self._main(transport, "llm-test")

        self.assertEqual(code, 0)
        self.assertEqual(transport.unloads, [])
        self.assertIn("llm_calls: 1", output)
        self.assertIn("unload_requests: 0", output)

    def test_unload_failure_is_one_warning_and_exit_code_stays_zero(self):
        transport = RoutingTransport(
            texts=["LOCAL_LLM_OK"],
            unload_error=ProviderRequestError("Ollama HTTP 500: unload rejected"),
        )

        code, output = self._main(transport, "llm-test")

        self.assertEqual(code, 0)
        self.assertEqual(len(transport.unloads), 1)
        warnings = [line for line in output.splitlines() if line.startswith("warning:")]
        self.assertEqual(len(warnings), 1)
        self.assertIn("unload", warnings[0])
        self.assertIn("unload_requests: 1", output)
        self.assertIn("LOCAL_LLM_OK", output)

    def test_model_override_unloads_the_model_that_was_requested(self):
        transport = RoutingTransport(texts=["LOCAL_LLM_OK"], models=(MODEL, "other:1b"))

        code, _output = self._main(transport, "llm-test", "--model", "other:1b")

        self.assertEqual(code, 0)
        self.assertEqual(transport.generations[0]["payload"]["model"], "other:1b")
        self.assertEqual(
            [call["payload"] for call in transport.unloads],
            [{"model": "other:1b", "keep_alive": 0}],
        )


class LLMStatusReportTests(RunUnloadTestCase):
    def test_status_reports_endpoint_model_and_gpu_release_settings(self):
        transport = RoutingTransport()

        code, output = self._main(transport, "llm-status")

        self.assertEqual(code, 0)
        self.assertEqual(transport.paths, ["/api/version", "/api/tags"])
        for expected in (
            f"endpoint: {ENDPOINT}",
            f"configured_model: {MODEL}",
            "keep_alive: 2m",
            "unload_after_run: true",
        ):
            self.assertIn(expected, output)

    def test_status_shows_unset_keep_alive_for_previous_config_shape(self):
        self._config(
            {
                "provider": "ollama",
                "base_url": "http://localhost:11434",
                "model": MODEL,
                "temperature": 0.0,
                "timeout": 180.0,
            }
        )

        _code, output = self._main(RoutingTransport(), "llm-status")

        self.assertIn("keep_alive: (not set)", output)
        self.assertIn("unload_after_run: false", output)


if __name__ == "__main__":
    unittest.main()
