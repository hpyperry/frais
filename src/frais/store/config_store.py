from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..providers import Provider, get_provider

CONFIG_PATH = Path.home() / ".frais" / "config" / "config.toml"


@dataclass
class ProviderConfig:
    provider: Provider
    model: str
    api_key: str
    api_key_source: str | None = None
    thinking: bool = True

    @property
    def is_ready(self) -> bool:
        return bool(self.api_key and self.model)


def _read_config_file(path: Path = CONFIG_PATH) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("rb") as handle:
        return tomllib.load(handle)


def load_config(path: Path = CONFIG_PATH) -> ProviderConfig | None:
    """Load provider config from TOML file. Returns None if not configured."""
    file_data = _read_config_file(path).get("llm", {})
    if not file_data:
        return None

    provider_id = file_data.get("provider", "")
    provider = get_provider(provider_id)
    if provider is None:
        return None

    model = file_data.get("model", "")
    env_key = os.getenv("FRAIS_LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    file_key = file_data.get("api_key")
    api_key = env_key or file_key or ""
    thinking = file_data.get("thinking", True)

    api_key_source = None
    if os.getenv("FRAIS_LLM_API_KEY"):
        api_key_source = "FRAIS_LLM_API_KEY"
    elif os.getenv("OPENAI_API_KEY"):
        api_key_source = "OPENAI_API_KEY"
    elif file_key:
        api_key_source = str(path)

    return ProviderConfig(
        provider=provider,
        model=model,
        api_key=api_key,
        api_key_source=api_key_source,
        thinking=thinking,
    )


def require_config(path: Path = CONFIG_PATH) -> ProviderConfig:
    config = load_config(path)
    if config is None or not config.api_key or not config.model:
        raise ValueError(
            "No LLM provider configured. Run `frais config manage` "
            "to set up your provider and API key."
        )
    return config


def _toml_escape(value: str) -> str:
    """Escape backslashes and double-quotes for TOML string values."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def save_config(provider_id: str, model: str, api_key: str, thinking: bool = True,
                path: Path = CONFIG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    thinking_str = "true" if thinking else "false"
    content = (
        "[llm]\n"
        f'provider = "{_toml_escape(provider_id)}"\n'
        f'model = "{_toml_escape(model)}"\n'
        f'api_key = "{_toml_escape(api_key)}"\n'
        f'thinking = {thinking_str}\n'
    )
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)
