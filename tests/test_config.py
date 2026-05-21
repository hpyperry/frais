from __future__ import annotations

from pathlib import Path

from frais.config import load_llm_config, write_config_template


def test_env_overrides_config(monkeypatch, tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        """
[llm]
provider = "file"
base_url = "https://file.example/v1"
model = "file-model"
api_key = "file-secret"
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("FRAIS_LLM_PROVIDER", "env")
    monkeypatch.setenv("FRAIS_LLM_BASE_URL", "https://env.example/v1")
    monkeypatch.setenv("FRAIS_LLM_MODEL", "env-model")
    monkeypatch.setenv("FRAIS_LLM_API_KEY", "env-secret-1234")

    loaded = load_llm_config(config)

    assert loaded.provider == "env"
    assert loaded.base_url == "https://env.example/v1"
    assert loaded.model == "env-model"
    assert loaded.api_key_source == "FRAIS_LLM_API_KEY"
    assert loaded.api_key_suffix == "1234"
    assert loaded.safe_dict()["api_key"] == "***1234"


def test_config_template_has_api_key_placeholder(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"

    write_config_template(config)

    text = config.read_text(encoding="utf-8")
    assert 'api_key = ""' in text
    assert 'base_url = "https://api.deepseek.com"' in text
