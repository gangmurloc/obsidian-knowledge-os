from __future__ import annotations

import json
import re
import socket
from collections.abc import Callable, Mapping
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .base import (
    GenerateRequest,
    GenerateResponse,
    HealthCheckResult,
    LLMProvider,
    MalformedResponseError,
    ModelInfo,
    ModelNotConfiguredError,
    ModelNotInstalledError,
    ProviderRequestError,
    ProviderTimeoutError,
)
from .config import LLMConfig


JsonTransport = Callable[[str, str, Mapping[str, Any] | None, float], Mapping[str, Any]]
MAX_RESPONSE_BYTES = 32 * 1024 * 1024
CLOUD_MODEL_PATTERN = re.compile(r"(?:^|[:/_-])cloud(?:$|[:/_-])", re.IGNORECASE)


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


LOCAL_ONLY_OPENER = build_opener(ProxyHandler({}), _NoRedirectHandler())


def _urllib_json_transport(
    method: str,
    url: str,
    payload: Mapping[str, Any] | None,
    timeout: float,
) -> Mapping[str, Any]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=body,
        method=method,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
    )
    try:
        with LOCAL_ONLY_OPENER.open(request, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as exc:
        try:
            detail = exc.read(4096).decode("utf-8", errors="replace")
        except OSError:
            detail = ""
        suffix = f": {detail}" if detail else ""
        raise ProviderRequestError(f"Ollama HTTP {exc.code}{suffix}") from exc
    except (TimeoutError, socket.timeout) as exc:
        raise ProviderTimeoutError(f"Ollama request timed out after {timeout:g}s.") from exc
    except URLError as exc:
        if isinstance(exc.reason, (TimeoutError, socket.timeout)):
            raise ProviderTimeoutError(f"Ollama request timed out after {timeout:g}s.") from exc
        raise ProviderRequestError(f"Cannot reach local Ollama server: {exc.reason}") from exc
    except OSError as exc:
        raise ProviderRequestError(f"Cannot reach local Ollama server: {exc}") from exc

    if len(raw) > MAX_RESPONSE_BYTES:
        raise MalformedResponseError("Ollama response exceeded the 32 MiB safety limit.")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MalformedResponseError("Ollama returned malformed JSON.") from exc
    if not isinstance(value, dict):
        raise MalformedResponseError("Ollama response root must be a JSON object.")
    return value


def _optional_int(value: Any, *, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise MalformedResponseError(f"Ollama field {field!r} must be an integer.")
    return value


def _installed_names(models: list[ModelInfo]) -> str:
    return ", ".join(model.name for model in models) or "(none)"


def _reject_cloud_model(model: str) -> None:
    if CLOUD_MODEL_PATTERN.search(model):
        raise ModelNotInstalledError(
            f"Cloud model {model!r} is blocked by the local-only v1 policy."
        )


class OllamaProvider(LLMProvider):
    def __init__(
        self,
        config: LLMConfig,
        *,
        transport: JsonTransport | None = None,
    ) -> None:
        self._config = config
        self._transport = transport or _urllib_json_transport

    @property
    def name(self) -> str:
        return "ollama"

    @property
    def endpoint(self) -> str:
        return self._config.base_url

    def _request(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> Mapping[str, Any]:
        return self._transport(
            method,
            f"{self.endpoint}{path}",
            payload,
            timeout if timeout is not None else self._config.timeout,
        )

    def health_check(self) -> HealthCheckResult:
        try:
            response = self._request(
                "GET",
                "/api/version",
                timeout=min(self._config.timeout, 3.0),
            )
            version = response.get("version")
            if not isinstance(version, str) or not version:
                raise MalformedResponseError("Ollama version response is missing 'version'.")
        except ProviderRequestError as exc:
            return HealthCheckResult(
                provider=self.name,
                endpoint=self.endpoint,
                reachable=False,
                error=str(exc),
            )
        return HealthCheckResult(
            provider=self.name,
            endpoint=self.endpoint,
            reachable=True,
            version=version,
        )

    def list_models(self) -> list[ModelInfo]:
        response = self._request("GET", "/api/tags")
        values = response.get("models")
        if not isinstance(values, list):
            raise MalformedResponseError("Ollama model response is missing a 'models' array.")

        models: list[ModelInfo] = []
        for index, value in enumerate(values):
            if not isinstance(value, dict):
                raise MalformedResponseError(f"Ollama model at index {index} is not an object.")
            name = value.get("name") or value.get("model")
            if not isinstance(name, str) or not name:
                raise MalformedResponseError(f"Ollama model at index {index} has no name.")
            size = value.get("size")
            if size is not None and (isinstance(size, bool) or not isinstance(size, int)):
                raise MalformedResponseError(f"Ollama model {name!r} has an invalid size.")
            digest = value.get("digest")
            modified_at = value.get("modified_at")
            models.append(
                ModelInfo(
                    name=name,
                    size=size,
                    digest=digest if isinstance(digest, str) else None,
                    modified_at=modified_at if isinstance(modified_at, str) else None,
                )
            )
        return models

    def generate(self, request: GenerateRequest) -> GenerateResponse:
        if not isinstance(request.prompt, str) or not request.prompt.strip():
            raise ValueError("prompt must not be empty")

        models = self.list_models()
        model = (request.model or self._config.model or "").strip()
        if not model:
            raise ModelNotConfiguredError(
                f"No model configured. Installed models: {_installed_names(models)}"
            )
        _reject_cloud_model(model)
        if model not in {item.name for item in models}:
            raise ModelNotInstalledError(
                f"Model {model!r} is not installed. Installed models: {_installed_names(models)}"
            )

        temperature = (
            request.temperature
            if request.temperature is not None
            else self._config.temperature
        )
        timeout = request.timeout if request.timeout is not None else self._config.timeout
        payload: dict[str, Any] = {
            "model": model,
            "prompt": request.prompt,
            "stream": False,
            "options": {"temperature": temperature},
        }
        if request.system:
            payload["system"] = request.system

        response = self._request("POST", "/api/generate", payload, timeout=timeout)
        text = response.get("response")
        response_model = response.get("model")
        done = response.get("done")
        if not isinstance(text, str):
            raise MalformedResponseError("Ollama generate response is missing text.")
        if not isinstance(response_model, str) or not response_model:
            raise MalformedResponseError("Ollama generate response is missing model.")
        if not isinstance(done, bool):
            raise MalformedResponseError("Ollama generate response is missing done state.")

        return GenerateResponse(
            provider=self.name,
            model=response_model,
            text=text,
            done=done,
            total_duration_ns=_optional_int(response.get("total_duration"), field="total_duration"),
            prompt_eval_count=_optional_int(response.get("prompt_eval_count"), field="prompt_eval_count"),
            eval_count=_optional_int(response.get("eval_count"), field="eval_count"),
        )
