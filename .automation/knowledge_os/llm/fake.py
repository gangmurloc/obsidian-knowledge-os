from __future__ import annotations

from .base import (
    GenerateRequest,
    GenerateResponse,
    HealthCheckResult,
    LLMProvider,
    ModelInfo,
    ModelNotConfiguredError,
    ModelNotInstalledError,
)


class FakeLLMProvider(LLMProvider):
    """Deterministic provider for tests; it never opens a network connection."""

    def __init__(
        self,
        *,
        models: tuple[str, ...] = ("fake-local:latest",),
        default_model: str | None = "fake-local:latest",
        response_text: str = "FAKE_RESPONSE",
        response_texts: tuple[str, ...] | None = None,
        reachable: bool = True,
        done_reason: str | None = "stop",
    ) -> None:
        self._models = models
        self._default_model = default_model
        self._response_text = response_text
        self._response_texts = list(response_texts) if response_texts is not None else None
        self._reachable = reachable
        self._done_reason = done_reason
        self.requests: list[GenerateRequest] = []

    @property
    def name(self) -> str:
        return "fake"

    @property
    def endpoint(self) -> str:
        return "memory://fake"

    def health_check(self) -> HealthCheckResult:
        return HealthCheckResult(
            provider=self.name,
            endpoint=self.endpoint,
            reachable=self._reachable,
            version="test" if self._reachable else None,
            error=None if self._reachable else "Fake provider is unavailable.",
        )

    def list_models(self) -> list[ModelInfo]:
        return [ModelInfo(name=name) for name in self._models]

    def generate(self, request: GenerateRequest) -> GenerateResponse:
        self.requests.append(request)
        model = request.model or self._default_model
        if not model:
            names = ", ".join(self._models) or "(none)"
            raise ModelNotConfiguredError(
                f"No model configured. Installed models: {names}"
            )
        if model not in self._models:
            names = ", ".join(self._models) or "(none)"
            raise ModelNotInstalledError(
                f"Model {model!r} is not installed. Installed models: {names}"
            )
        if not request.prompt.strip():
            raise ValueError("prompt must not be empty")
        if self._response_texts is not None:
            if not self._response_texts:
                raise RuntimeError("FakeLLMProvider has no scripted response remaining.")
            response_text = self._response_texts.pop(0)
        else:
            response_text = self._response_text
        return GenerateResponse(
            provider=self.name,
            model=model,
            text=response_text,
            done=True,
            done_reason=self._done_reason,
        )
