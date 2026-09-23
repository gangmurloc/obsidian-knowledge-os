from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


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
    ProviderTimeoutError,
    load_llm_config,
)
from knowledge_os.llm.config import (  # noqa: E402
    parse_llm_config,
    save_llm_config,
    validate_loopback_base_url,
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


if __name__ == "__main__":
    unittest.main()
