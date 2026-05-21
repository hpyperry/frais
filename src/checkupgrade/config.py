from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .models import LLMConfig

CONFIG_PATH = Path.home() / ".config" / "checkupgrade" / "config.toml"


@dataclass(slots=True)
class RawLLMConfig:
    provider: str = "openai-compatible"
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None
    api_key_source: str | None = None
    thinking: bool = False


def _read_config_file(path: Path = CONFIG_PATH) -> dict:
    if not path.exists():
        return {}
    with path.open("rb") as handle:
        return tomllib.load(handle)


def load_raw_config(path: Path = CONFIG_PATH) -> RawLLMConfig:
    file_data = _read_config_file(path).get("llm", {})
    provider = os.getenv("CHECKUPGRADE_LLM_PROVIDER") or file_data.get("provider") or "openai-compatible"
    base_url = os.getenv("CHECKUPGRADE_LLM_BASE_URL") or file_data.get("base_url")
    model = os.getenv("CHECKUPGRADE_LLM_MODEL") or file_data.get("model")

    env_key = os.getenv("CHECKUPGRADE_LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    file_key = file_data.get("api_key")
    api_key = env_key or file_key
    api_key_source = None
    if os.getenv("CHECKUPGRADE_LLM_API_KEY"):
        api_key_source = "CHECKUPGRADE_LLM_API_KEY"
    elif os.getenv("OPENAI_API_KEY"):
        api_key_source = "OPENAI_API_KEY"
    elif file_key:
        api_key_source = str(path)

    thinking_str = os.getenv("CHECKUPGRADE_LLM_THINKING") or file_data.get("thinking")
    thinking = thinking_str in (True, "true", "1", "yes") if isinstance(thinking_str, str) else bool(thinking_str)

    return RawLLMConfig(
        provider=provider,
        base_url=base_url,
        model=model,
        api_key=api_key,
        api_key_source=api_key_source,
        thinking=thinking,
    )


def load_llm_config(path: Path = CONFIG_PATH) -> LLMConfig:
    raw = load_raw_config(path)
    suffix = raw.api_key[-4:] if raw.api_key and len(raw.api_key) >= 4 else None
    return LLMConfig(
        provider=raw.provider,
        base_url=raw.base_url,
        model=raw.model,
        api_key_source=raw.api_key_source,
        has_api_key=bool(raw.api_key),
        api_key_suffix=suffix,
        thinking=raw.thinking,
    )


def require_raw_llm_config(path: Path = CONFIG_PATH) -> RawLLMConfig:
    raw = load_raw_config(path)
    missing = []
    if not raw.api_key:
        missing.append("CHECKUPGRADE_LLM_API_KEY")
    if not raw.base_url:
        missing.append("CHECKUPGRADE_LLM_BASE_URL")
    if not raw.model:
        missing.append("CHECKUPGRADE_LLM_MODEL")
    if missing:
        names = ", ".join(missing)
        raise ValueError(
            f"Missing BYOK LLM configuration: {names}. Run `checkupgrade config init` "
            "or set the CHECKUPGRADE_LLM_* environment variables."
        )
    return raw


def write_config_template(path: Path = CONFIG_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return path
    template = """[llm]
provider = "openai-compatible"
base_url = "https://api.example.com/v1"
model = "your-model-name"
# Prefer CHECKUPGRADE_LLM_API_KEY in your shell for better secret hygiene.
# If you store a key here, keep this file private and never commit it.
api_key = ""

# Thinking mode — enable for models that support extended reasoning.
# Set to true to let the model think before answering (improves quality).
# Structured calls (search queries, URL selection, version extraction)
# always disable thinking to ensure clean JSON output.
# thinking = false

# DeepSeek example:
# base_url = "https://api.deepseek.com"
# model = "deepseek-v4-flash"
"""
    path.write_text(template, encoding="utf-8")
    return path
