from __future__ import annotations

from typing import Any

from .base import LLMProvider
from .config import LLMConfig, LLMConfigError
from .ollama import JsonTransport, OllamaProvider


def create_provider(
    config: LLMConfig,
    *,
    transport: JsonTransport | None = None,
) -> LLMProvider:
    if config.provider == "ollama":
        return OllamaProvider(config, transport=transport)
    raise LLMConfigError(f"Unsupported Local LLM provider: {config.provider!r}")
