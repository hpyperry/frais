from __future__ import annotations

from pathlib import Path

import pytest

from frais.providers import PROVIDERS, get_provider
from frais.store.config_store import load_config, require_config, save_config


def test_load_config_returns_none_for_missing_file() -> None:
    assert load_config(Path("/nonexistent/config.toml")) is None


def test_load_config_parses_valid_file(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        """
[llm]
provider = "deepseek"
model = "deepseek-v4-flash"
api_key = "sk-test-1234"
""",
        encoding="utf-8",
    )

    loaded = load_config(config)
    assert loaded is not None
    assert loaded.provider.id == "deepseek"
    assert loaded.provider.name == "DeepSeek"
    assert loaded.model == "deepseek-v4-flash"
    assert loaded.api_key == "sk-test-1234"
    assert loaded.is_ready


def test_load_config_returns_none_for_unknown_provider(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        """
[llm]
provider = "nonexistent"
model = "some-model"
api_key = "sk-1234"
""",
        encoding="utf-8",
    )

    assert load_config(config) is None


def test_load_config_env_var_overrides_key(tmp_path: Path, monkeypatch) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        """
[llm]
provider = "deepseek"
model = "deepseek-v4-flash"
api_key = "file-key-1234"
""",
        encoding="utf-8",
    )

    monkeypatch.setenv("FRAIS_LLM_API_KEY", "env-key-5678")
    loaded = load_config(config)
    assert loaded is not None
    assert loaded.api_key == "env-key-5678"
    assert loaded.api_key_source == "FRAIS_LLM_API_KEY"


def test_load_config_generic_env_var_falls_back(tmp_path: Path, monkeypatch) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        """
[llm]
provider = "deepseek"
model = "deepseek-v4-flash"
api_key = ""
""",
        encoding="utf-8",
    )

    monkeypatch.setenv("OPENAI_API_KEY", "openai-env-key")
    loaded = load_config(config)
    assert loaded is not None
    assert loaded.api_key == "openai-env-key"
    assert loaded.api_key_source == "OPENAI_API_KEY"


def test_save_config_creates_file(tmp_path: Path) -> None:
    config = tmp_path / "subdir" / "config.toml"
    save_config("deepseek", "deepseek-v4-pro", "sk-abcdef", path=config)

    assert config.exists()
    text = config.read_text(encoding="utf-8")
    assert 'provider = "deepseek"' in text
    assert 'model = "deepseek-v4-pro"' in text
    assert 'api_key = "sk-abcdef"' in text
    assert 'thinking = true' in text


def test_save_config_writes_thinking_false(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    save_config("deepseek", "deepseek-v4-flash", "sk-key", thinking=False, path=config)
    text = config.read_text(encoding="utf-8")
    assert 'thinking = false' in text


def test_load_config_reads_thinking_true(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        """
[llm]
provider = "deepseek"
model = "deepseek-v4-flash"
api_key = "sk-test"
thinking = true
""",
        encoding="utf-8",
    )
    loaded = load_config(config)
    assert loaded is not None
    assert loaded.thinking is True


def test_load_config_reads_thinking_false(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        """
[llm]
provider = "deepseek"
model = "deepseek-v4-flash"
api_key = "sk-test"
thinking = false
""",
        encoding="utf-8",
    )
    loaded = load_config(config)
    assert loaded is not None
    assert loaded.thinking is False


def test_load_config_defaults_thinking_true(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        """
[llm]
provider = "deepseek"
model = "deepseek-v4-flash"
api_key = "sk-test"
""",
        encoding="utf-8",
    )
    loaded = load_config(config)
    assert loaded is not None
    assert loaded.thinking is True


def test_require_config_raises_when_missing() -> None:
    with pytest.raises(ValueError, match="No LLM provider configured"):
        require_config(Path("/nonexistent/config.toml"))


def test_require_config_succeeds_with_valid_config(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        """
[llm]
provider = "deepseek"
model = "deepseek-v4-pro"
api_key = "sk-key"
""",
        encoding="utf-8",
    )

    result = require_config(config)
    assert result.provider.id == "deepseek"
    assert result.model == "deepseek-v4-pro"


def test_all_registered_providers_loadable() -> None:
    """Verify every provider in the registry resolves via get_provider."""
    for p in PROVIDERS:
        found = get_provider(p.id)
        assert found is not None, f"provider {p.id} not found"
        assert found is p
