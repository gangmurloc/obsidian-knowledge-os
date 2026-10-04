from __future__ import annotations

import ipaddress
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

from ..io_utils import atomic_write_json
from .base import LLMError


DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_CONFIG_RELATIVE_PATH = Path(".automation/config/local_llm.json")
ALLOWED_CONFIG_KEYS = {
    "provider",
    "base_url",
    "model",
    "temperature",
    "timeout",
    "keep_alive",
    "unload_after_run",
}
MAX_KEEP_ALIVE_SECONDS = 3600
# At most four significant digits, so an oversized duration never reaches int().
KEEP_ALIVE_DURATION_PATTERN = re.compile(r"0*([0-9]{1,4})(s|m)")


class LLMConfigError(LLMError):
    """Local LLM configuration is missing or invalid."""


@dataclass(frozen=True)
class LLMConfig:
    provider: str = "ollama"
    base_url: str = DEFAULT_OLLAMA_BASE_URL
    model: str | None = None
    temperature: float = 0.2
    timeout: float = 60.0
    keep_alive: int | str | None = None
    unload_after_run: bool = False


def validate_loopback_base_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except (TypeError, ValueError) as exc:
        raise LLMConfigError(f"Invalid Local LLM base_url: {value!r}") from exc

    if parsed.scheme not in {"http", "https"}:
        raise LLMConfigError("Local LLM base_url must use http or https.")
    if not parsed.hostname:
        raise LLMConfigError("Local LLM base_url must include a hostname.")
    if parsed.username or parsed.password:
        raise LLMConfigError("Credentials are not allowed in Local LLM base_url.")
    if parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise LLMConfigError("Local LLM base_url must not include a path, query, or fragment.")

    hostname = parsed.hostname.casefold()
    if hostname != "localhost":
        try:
            address = ipaddress.ip_address(hostname)
        except ValueError as exc:
            raise LLMConfigError(
                f"External LLM endpoint is blocked in v1: {parsed.hostname}"
            ) from exc
        if not address.is_loopback:
            raise LLMConfigError(
                f"External LLM endpoint is blocked in v1: {parsed.hostname}"
            )

    return value.rstrip("/")


def _number(value: Any, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LLMConfigError(f"{field} must be a number.")
    return float(value)


def _keep_alive(value: Any) -> int | str | None:
    """Accept only a bounded duration so a shared GPU is never held indefinitely."""
    if value is None:
        return None
    seconds: int | None = None
    if isinstance(value, int) and not isinstance(value, bool):
        seconds = value
    elif isinstance(value, str):
        match = KEEP_ALIVE_DURATION_PATTERN.fullmatch(value)
        if match:
            seconds = int(match.group(1)) * (60 if match.group(2) == "m" else 1)
    if seconds is None or not 0 <= seconds <= MAX_KEEP_ALIVE_SECONDS:
        raise LLMConfigError(
            "keep_alive must be an integer from 0 to 3600 seconds or a duration "
            "such as '30s' or '2m' (at most '60m')."
        )
    return value


def parse_llm_config(value: Mapping[str, Any]) -> LLMConfig:
    unknown = set(value) - ALLOWED_CONFIG_KEYS
    if unknown:
        raise LLMConfigError(f"Unknown Local LLM config field(s): {', '.join(sorted(unknown))}")

    provider = value.get("provider", "ollama")
    if not isinstance(provider, str) or provider.casefold() != "ollama":
        raise LLMConfigError(f"Unsupported Local LLM provider: {provider!r}")

    base_url_value = value.get("base_url", DEFAULT_OLLAMA_BASE_URL)
    if not isinstance(base_url_value, str):
        raise LLMConfigError("base_url must be a string.")
    base_url = validate_loopback_base_url(base_url_value)

    model_value = value.get("model")
    if model_value is not None and not isinstance(model_value, str):
        raise LLMConfigError("model must be a string or null.")
    model = model_value.strip() if isinstance(model_value, str) else None
    model = model or None

    temperature = _number(value.get("temperature", 0.2), field="temperature")
    if not 0 <= temperature <= 2:
        raise LLMConfigError("temperature must be between 0 and 2.")

    timeout = _number(value.get("timeout", 60.0), field="timeout")
    if not 0 < timeout <= 600:
        raise LLMConfigError("timeout must be greater than 0 and at most 600 seconds.")

    keep_alive = _keep_alive(value.get("keep_alive"))

    unload_after_run = value.get("unload_after_run", False)
    if not isinstance(unload_after_run, bool):
        raise LLMConfigError("unload_after_run must be true or false.")

    return LLMConfig(
        provider="ollama",
        base_url=base_url,
        model=model,
        temperature=temperature,
        timeout=timeout,
        keep_alive=keep_alive,
        unload_after_run=unload_after_run,
    )


def load_llm_config(path: Path) -> LLMConfig:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise LLMConfigError(f"Cannot read Local LLM config {path}: {exc}") from exc
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LLMConfigError(f"Invalid JSON in Local LLM config {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise LLMConfigError("Local LLM config root must be a JSON object.")
    return parse_llm_config(value)


def save_llm_config(path: Path, config: LLMConfig) -> None:
    """Atomically replace config on the same filesystem, preserving it on failure."""
    atomic_write_json(path, asdict(config), overwrite=True)


def resolve_config_path(vault_root: Path, configured_path: Path | None) -> Path:
    if configured_path is None:
        return vault_root.resolve() / DEFAULT_CONFIG_RELATIVE_PATH
    if configured_path.is_absolute():
        return configured_path.resolve()
    return vault_root.resolve() / configured_path
