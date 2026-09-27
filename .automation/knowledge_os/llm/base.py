from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


class LLMError(RuntimeError):
    """Base error for local LLM configuration and provider failures."""


class ProviderRequestError(LLMError):
    """The local provider could not complete an HTTP request."""


class ProviderTimeoutError(ProviderRequestError):
    """The local provider exceeded the configured timeout."""


class MalformedResponseError(ProviderRequestError):
    """The provider returned JSON that does not match the expected schema."""


class ModelNotConfiguredError(LLMError):
    """Generation was requested without an explicit model."""


class ModelNotInstalledError(LLMError):
    """The configured model is not available from the local provider."""


@dataclass(frozen=True)
class HealthCheckResult:
    provider: str
    endpoint: str
    reachable: bool
    version: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class ModelInfo:
    name: str
    size: int | None = None
    digest: str | None = None
    modified_at: str | None = None


@dataclass(frozen=True)
class GenerateRequest:
    prompt: str
    model: str | None = None
    system: str | None = None
    temperature: float | None = None
    timeout: float | None = None
    max_output_tokens: int | None = None
    response_format: str | Mapping[str, Any] | None = None
    think: bool | str | None = False


@dataclass(frozen=True)
class GenerateResponse:
    provider: str
    model: str
    text: str
    done: bool
    done_reason: str | None = None
    total_duration_ns: int | None = None
    prompt_eval_count: int | None = None
    eval_count: int | None = None


class LLMProvider(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def endpoint(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def health_check(self) -> HealthCheckResult:
        raise NotImplementedError

    @abstractmethod
    def list_models(self) -> list[ModelInfo]:
        raise NotImplementedError

    @abstractmethod
    def generate(self, request: GenerateRequest) -> GenerateResponse:
        raise NotImplementedError
