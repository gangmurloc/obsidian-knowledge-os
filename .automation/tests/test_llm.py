from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.request import ProxyHandler


AUTOMATION_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AUTOMATION_ROOT))

from knowledge_os.llm import (  # noqa: E402
    FakeLLMProvider,
    GenerateRequest,
    LLMConfig,
    LLMConfigError,
    MalformedResponseError,
    ModelNotConfiguredError,
    ModelNotInstalledError,
    OllamaProvider,
    ProviderRequestError,
    ProviderTimeoutError,
    load_llm_config,
    request_unload,
)
from knowledge_os.llm.config import (  # noqa: E402
    parse_llm_config,
    save_llm_config,
    validate_loopback_base_url,
)
from knowledge_os.llm.ollama import (  # noqa: E402
    LOCAL_ONLY_OPENER,
    _NoRedirectHandler,
)


class RecordingTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, method, url, payload, timeout):
        self.calls.append(
            {"method": method, "url": url, "payload": payload, "timeout": timeout}
        )
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class LocalLLMTests(unittest.TestCase):
    def test_fake_provider_health_check_and_generation(self):
        provider = FakeLLMProvider(response_text="LOCAL_LLM_OK")
        health = provider.health_check()
        response = provider.generate(GenerateRequest(prompt="test"))

        self.assertTrue(health.reachable)
        self.assertEqual(health.provider, "fake")
        self.assertEqual(response.text, "LOCAL_LLM_OK")
        self.assertEqual(response.model, "fake-local:latest")

    def test_invalid_provider_is_rejected(self):
        with self.assertRaisesRegex(LLMConfigError, "Unsupported"):
            parse_llm_config({"provider": "openai"})

    def test_loopback_endpoints_are_allowed(self):
        self.assertEqual(
            validate_loopback_base_url("http://localhost:11434/"),
            "http://localhost:11434",
        )
        self.assertEqual(
            validate_loopback_base_url("http://127.0.0.1:11434"),
            "http://127.0.0.1:11434",
        )
        self.assertEqual(
            validate_loopback_base_url("http://[::1]:11434"),
            "http://[::1]:11434",
        )

    def test_external_endpoints_are_blocked(self):
        endpoints = [
            "https://api.openai.com",
            "https://api.anthropic.com",
            "https://generativelanguage.googleapis.com",
            "https://openrouter.ai",
            "http://192.168.0.20:11434",
            "http://localhost.example.com:11434",
        ]
        for endpoint in endpoints:
            with self.subTest(endpoint=endpoint):
                with self.assertRaisesRegex(LLMConfigError, "blocked"):
                    validate_loopback_base_url(endpoint)

    def test_missing_model_lists_installed_models_without_generation(self):
        transport = RecordingTransport(
            [
                {
                    "models": [
                        {"name": "local-a:latest", "size": 10},
                        {"name": "local-b:latest", "size": 20},
                    ]
                }
            ]
        )
        provider = OllamaProvider(LLMConfig(model=None), transport=transport)

        with self.assertRaisesRegex(
            ModelNotConfiguredError,
            "local-a:latest, local-b:latest",
        ):
            provider.generate(GenerateRequest(prompt="test"))
        self.assertEqual(len(transport.calls), 1)
        self.assertTrue(transport.calls[0]["url"].endswith("/api/tags"))

    def test_cloud_model_is_blocked_even_when_listed(self):
        transport = RecordingTransport(
            [{"models": [{"name": "example:7b-cloud"}]}]
        )
        provider = OllamaProvider(
            LLMConfig(model="example:7b-cloud"),
            transport=transport,
        )
        with self.assertRaisesRegex(ModelNotInstalledError, "local-only"):
            provider.generate(GenerateRequest(prompt="test"))
        self.assertEqual(len(transport.calls), 1)

    def test_malformed_model_response_is_rejected(self):
        provider = OllamaProvider(
            LLMConfig(),
            transport=RecordingTransport([{"models": "not-an-array"}]),
        )
        with self.assertRaises(MalformedResponseError):
            provider.list_models()

    def test_malformed_generate_response_is_rejected(self):
        transport = RecordingTransport(
            [
                {"models": [{"name": "local-a:latest"}]},
                {"model": "local-a:latest", "done": True},
            ]
        )
        provider = OllamaProvider(
            LLMConfig(model="local-a:latest"),
            transport=transport,
        )
        with self.assertRaises(MalformedResponseError):
            provider.generate(GenerateRequest(prompt="test"))

    def test_timeout_is_configurable_and_propagated(self):
        transport = RecordingTransport(
            [
                {"models": [{"name": "local-a:latest"}]},
                ProviderTimeoutError("timed out"),
            ]
        )
        provider = OllamaProvider(
            LLMConfig(model="local-a:latest", timeout=30.0),
            transport=transport,
        )
        with self.assertRaises(ProviderTimeoutError):
            provider.generate(GenerateRequest(prompt="test", timeout=1.5))
        self.assertEqual(transport.calls[-1]["timeout"], 1.5)

    def test_structured_output_and_thinking_policy_reach_ollama_payload(self):
        schema = {"type": "object", "properties": {"concepts": {"type": "array"}}}
        transport = RecordingTransport(
            [
                {"models": [{"name": "local-a:latest"}]},
                {
                    "model": "local-a:latest",
                    "response": '{"concepts": []}',
                    "done": True,
                    "done_reason": "length",
                },
            ]
        )
        provider = OllamaProvider(
            LLMConfig(model="local-a:latest"),
            transport=transport,
        )
        response = provider.generate(
            GenerateRequest(
                prompt="test",
                max_output_tokens=1024,
                response_format=schema,
                think=False,
            )
        )
        payload = transport.calls[-1]["payload"]
        self.assertEqual(payload["format"], schema)
        self.assertIs(payload["think"], False)
        self.assertEqual(payload["options"]["num_predict"], 1024)
        self.assertEqual(response.done_reason, "length")

    def test_invalid_output_token_limit_is_rejected_before_generation(self):
        transport = RecordingTransport(
            [{"models": [{"name": "local-a:latest"}]}]
        )
        provider = OllamaProvider(
            LLMConfig(model="local-a:latest"),
            transport=transport,
        )
        with self.assertRaisesRegex(ValueError, "positive integer"):
            provider.generate(GenerateRequest(prompt="test", max_output_tokens=0))
        self.assertEqual(len(transport.calls), 1)

    def test_config_parsing_and_atomic_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "local_llm.json"
            path.write_text(
                json.dumps(
                    {
                        "provider": "ollama",
                        "base_url": "http://127.0.0.1:11434",
                        "model": "local-a:latest",
                        "temperature": 0.4,
                        "timeout": 12,
                    }
                ),
                encoding="utf-8",
            )
            config = load_llm_config(path)
            self.assertEqual(config.model, "local-a:latest")
            self.assertEqual(config.temperature, 0.4)
            self.assertEqual(config.timeout, 12.0)

            replacement = LLMConfig(model="local-b:latest", timeout=15.0)
            save_llm_config(path, replacement)
            self.assertEqual(load_llm_config(path), replacement)


class KeepAliveAndUnloadTests(unittest.TestCase):
    def _generate_payload(self, config: LLMConfig) -> dict:
        transport = RecordingTransport(
            [
                {"models": [{"name": "local-a:latest"}]},
                {"model": "local-a:latest", "response": "ok", "done": True},
            ]
        )
        OllamaProvider(config, transport=transport).generate(
            GenerateRequest(
                prompt="test",
                system="system text",
                max_output_tokens=1024,
                response_format="json",
                think=False,
            )
        )
        return transport.calls[-1]["payload"]

    def test_keep_alive_accepts_bounded_seconds_and_durations(self):
        for value in (0, 120, 3600, "0s", "30s", "2m", "60m", "3600s"):
            with self.subTest(value=value):
                config = parse_llm_config({"keep_alive": value})
                self.assertEqual(config.keep_alive, value)
                self.assertIs(type(config.keep_alive), type(value))

    def test_keep_alive_rejects_unbounded_or_malformed_values(self):
        rejected = (
            -1,
            "-1",
            "forever",
            "61m",
            "2h",
            3601,
            True,
            False,
            "3601s",
            120.0,
            "120",
            "",
            "m",
            " 2m",
            "2m\n",
            "2M",
            ["2m"],
        )
        for value in rejected:
            with self.subTest(value=value):
                with self.assertRaisesRegex(LLMConfigError, "keep_alive"):
                    parse_llm_config({"keep_alive": value})

    def test_unload_after_run_must_be_boolean(self):
        self.assertIs(
            parse_llm_config({"unload_after_run": True}).unload_after_run,
            True,
        )
        for value in ("true", "false", 1, 0, None, []):
            with self.subTest(value=value):
                with self.assertRaisesRegex(LLMConfigError, "unload_after_run"):
                    parse_llm_config({"unload_after_run": value})

    def test_config_without_new_keys_loads_with_unchanged_defaults(self):
        config = parse_llm_config(
            {
                "provider": "ollama",
                "base_url": "http://localhost:11434",
                "model": "local-a:latest",
                "temperature": 0.0,
                "timeout": 180.0,
            }
        )
        self.assertIsNone(config.keep_alive)
        self.assertIs(config.unload_after_run, False)
        self.assertIsNone(parse_llm_config({"keep_alive": None}).keep_alive)

    def test_tunnel_config_round_trips_through_atomic_save(self):
        value = {
            "provider": "ollama",
            "base_url": "http://localhost:11435",
            "model": "local-a:latest",
            "temperature": 0.0,
            "timeout": 300.0,
            "keep_alive": "2m",
            "unload_after_run": True,
        }
        config = parse_llm_config(value)
        self.assertEqual(config.base_url, "http://localhost:11435")
        self.assertEqual(config.timeout, 300.0)
        self.assertEqual(config.keep_alive, "2m")
        self.assertIs(config.unload_after_run, True)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "local_llm.json"
            save_llm_config(path, config)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), value)
            self.assertEqual(load_llm_config(path), config)

    def test_unknown_config_key_is_still_rejected(self):
        with self.assertRaisesRegex(LLMConfigError, "Unknown"):
            parse_llm_config({"keep_alive": "2m", "fallback_url": "http://localhost:11434"})

    def test_tunnel_port_is_loopback_and_remote_hosts_stay_blocked(self):
        for endpoint in (
            "http://10.0.0.5:11434",
            "http://server.lab:11434",
            "http://0.0.0.0:11434",
        ):
            with self.subTest(endpoint=endpoint):
                with self.assertRaisesRegex(LLMConfigError, "blocked"):
                    validate_loopback_base_url(endpoint)
                with self.assertRaisesRegex(LLMConfigError, "blocked"):
                    parse_llm_config({"base_url": endpoint})
        for endpoint in ("http://localhost:11435", "http://127.0.0.1:11435"):
            with self.subTest(endpoint=endpoint):
                self.assertEqual(validate_loopback_base_url(endpoint), endpoint)

    def test_keep_alive_is_sent_at_payload_top_level_when_configured(self):
        for value in ("2m", 120, 0):
            with self.subTest(value=value):
                payload = self._generate_payload(
                    LLMConfig(model="local-a:latest", keep_alive=value)
                )
                self.assertEqual(payload["keep_alive"], value)
                self.assertNotIn("keep_alive", payload["options"])
                self.assertEqual(payload["prompt"], "test")

    def test_payload_is_byte_identical_when_keep_alive_is_not_configured(self):
        payload = self._generate_payload(LLMConfig(model="local-a:latest"))
        expected = {
            "model": "local-a:latest",
            "prompt": "test",
            "stream": False,
            "options": {"temperature": 0.2, "num_predict": 1024},
            "system": "system text",
            "format": "json",
            "think": False,
        }
        self.assertEqual(json.dumps(payload), json.dumps(expected))

    def test_unload_sends_only_model_and_zero_keep_alive(self):
        transport = RecordingTransport(
            [{"model": "local-a:latest", "response": "", "done": True, "done_reason": "unload"}]
        )
        provider = OllamaProvider(
            LLMConfig(
                base_url="http://localhost:11435",
                model="local-a:latest",
                timeout=300.0,
                keep_alive="2m",
            ),
            transport=transport,
        )

        self.assertIsNone(provider.unload("local-a:latest"))

        self.assertEqual(len(transport.calls), 1)
        call = transport.calls[0]
        self.assertEqual(call["method"], "POST")
        self.assertEqual(call["url"], "http://localhost:11435/api/generate")
        self.assertEqual(
            json.dumps(call["payload"]),
            json.dumps({"model": "local-a:latest", "keep_alive": 0}),
        )
        self.assertNotIn("prompt", call["payload"])
        self.assertEqual(call["timeout"], 10)

    def test_unload_timeout_never_exceeds_configured_timeout(self):
        transport = RecordingTransport([{"done": True}])
        provider = OllamaProvider(
            LLMConfig(model="local-a:latest", timeout=4.0),
            transport=transport,
        )
        provider.unload("local-a:latest")
        self.assertEqual(transport.calls[0]["timeout"], 4.0)

    def test_unload_failure_propagates_after_a_single_request(self):
        transport = RecordingTransport([ProviderRequestError("connection refused")])
        provider = OllamaProvider(LLMConfig(model="local-a:latest"), transport=transport)
        with self.assertRaises(ProviderRequestError):
            provider.unload("local-a:latest")
        self.assertEqual(len(transport.calls), 1)

    def test_unload_blocks_cloud_and_empty_models_before_any_request(self):
        transport = RecordingTransport([])
        provider = OllamaProvider(LLMConfig(), transport=transport)
        with self.assertRaisesRegex(ModelNotInstalledError, "local-only"):
            provider.unload("example:7b-cloud")
        with self.assertRaises(ModelNotConfiguredError):
            provider.unload("  ")
        self.assertEqual(transport.calls, [])

    def test_unload_uses_the_proxy_free_no_redirect_opener(self):
        self.assertTrue(
            any(isinstance(handler, _NoRedirectHandler) for handler in LOCAL_ONLY_OPENER.handlers)
        )
        self.assertFalse(
            any(isinstance(handler, ProxyHandler) for handler in LOCAL_ONLY_OPENER.handlers)
        )
        opened = []

        class _Response:
            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return False

            def read(self, _limit):
                return b'{"model": "local-a:latest", "done": true, "done_reason": "unload"}'

        class _Opener:
            def open(self, request, timeout):
                opened.append(
                    (request.get_method(), request.full_url, request.data, timeout)
                )
                return _Response()

        with patch("knowledge_os.llm.ollama.LOCAL_ONLY_OPENER", _Opener()):
            OllamaProvider(
                LLMConfig(base_url="http://localhost:11435", model="local-a:latest")
            ).unload("local-a:latest")

        self.assertEqual(
            opened,
            [
                (
                    "POST",
                    "http://localhost:11435/api/generate",
                    b'{"model": "local-a:latest", "keep_alive": 0}',
                    10,
                )
            ],
        )

    def test_fake_provider_unload_only_records_the_call(self):
        provider = FakeLLMProvider()
        self.assertIsNone(provider.unload("fake-local:latest"))
        self.assertEqual(provider.unload_requests, ["fake-local:latest"])
        self.assertEqual(provider.requests, [])

    def test_request_unload_returns_one_warning_line_without_retry(self):
        provider = FakeLLMProvider()
        self.assertIsNone(request_unload(provider, "fake-local:latest"))
        self.assertEqual(provider.unload_requests, ["fake-local:latest"])

        with patch.object(
            provider,
            "unload",
            side_effect=ProviderRequestError("Ollama HTTP 500: first line\nsecond line"),
        ) as unload:
            warning = request_unload(provider, "fake-local:latest")
        self.assertEqual(unload.call_count, 1)
        self.assertIn("unload", warning)
        self.assertIn("ProviderRequestError", warning)
        self.assertEqual(len(warning.splitlines()), 1)


if __name__ == "__main__":
    unittest.main()
