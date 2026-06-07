// LLM provider configuration store — matches Python's frais/store/config_store.py.
// Reads/writes ~/.frais/config/config.toml with atomic file operations.

use crate::providers::{get_provider, Provider};
use serde::{Deserialize, Serialize};
use std::path::Path;

/// Provider configuration — matches Python's ProviderConfig dataclass.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ProviderConfig {
    pub provider: String,
    pub model: String,
    #[serde(default)]
    pub api_key: String,
    #[serde(default)]
    pub api_key_source: Option<String>,
    #[serde(default = "default_protocol")]
    pub protocol: String,
    #[serde(default)]
    pub url: String,
    /// Summary language: "zh" or "en". Defaults to detected system locale.
    #[serde(default = "detect_language")]
    pub language: String,
}

fn default_protocol() -> String {
    "openai".into()
}

/// Detect summary language from system locale.
/// On macOS, checks AppleLocale first (the actual system language),
/// then falls back to the LANG environment variable.
/// Returns "zh" if the locale is Chinese, otherwise "en".
pub fn detect_language() -> String {
    // macOS: read system language from defaults
    if let Ok(locale) = std::process::Command::new("defaults")
        .args(["read", "-g", "AppleLocale"])
        .output()
    {
        let stdout = String::from_utf8_lossy(&locale.stdout);
        if stdout.trim().starts_with("zh") {
            return "zh".to_string();
        }
    }
    // Fallback: check LANG env var
    if std::env::var("LANG")
        .unwrap_or_default()
        .starts_with("zh_")
    {
        "zh"
    } else {
        "en"
    }
    .to_string()
}

impl ProviderConfig {
    /// Whether the config is ready to use (both key and model present).
    pub fn is_ready(&self) -> bool {
        !self.api_key.trim().is_empty() && !self.model.trim().is_empty()
    }

    /// Get the resolved provider from the registry.
    pub fn get_provider(&self) -> Option<Provider> {
        get_provider(&self.provider)
    }
}

/// Load config from a TOML file. Returns None if missing or invalid.
/// Matches Python's load_config() including env var override logic.
pub fn load_config(path: &Path) -> Option<ProviderConfig> {
    let content = match std::fs::read_to_string(path) {
        Ok(c) => c,
        Err(e) => {
            if e.kind() != std::io::ErrorKind::NotFound {
                log::warn!("Cannot read config file {}: {}", path.display(), e);
            }
            return None;
        }
    };
    let toml_value: toml::Value = match toml::from_str(&content) {
        Ok(v) => v,
        Err(e) => {
            log::warn!(
                "Config file {} is not valid TOML: {}. Run `frais config manage` to fix.",
                path.display(),
                e
            );
            return None;
        }
    };

    let llm_section = match toml_value.get("llm") {
        Some(s) => s,
        None => {
            log::warn!(
                "Config file {} missing [llm] section. Run `frais config manage` to set up.",
                path.display()
            );
            return None;
        }
    };
    let provider_id = match llm_section.get("provider").and_then(|v| v.as_str()) {
        Some(id) => id.to_string(),
        None => {
            log::warn!(
                "Config file {} missing provider field in [llm] section.",
                path.display()
            );
            return None;
        }
    };
    let model = match llm_section.get("model").and_then(|v| v.as_str()) {
        Some(m) => m.to_string(),
        None => {
            log::warn!(
                "Config file {} missing model field in [llm] section.",
                path.display()
            );
            return None;
        }
    };
    let file_key = llm_section
        .get("api_key")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    let protocol = llm_section
        .get("protocol")
        .and_then(|v| v.as_str())
        .unwrap_or("openai")
        .to_string();
    let url = llm_section
        .get("url")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    let language = llm_section
        .get("language")
        .and_then(|v| v.as_str())
        .unwrap_or_else(|| if detect_language() == "zh" { "zh" } else { "en" })
        .to_string();

    // API key resolution order matches Python exactly:
    // 1. FRAIS_LLM_API_KEY env var
    // 2. MIMO_API_KEY env var
    // 3. OPENAI_API_KEY env var
    // 4. File-stored key
    let (api_key, key_source) = if let Ok(key) = std::env::var("FRAIS_LLM_API_KEY") {
        (key, Some("FRAIS_LLM_API_KEY".into()))
    } else if let Ok(key) = std::env::var("MIMO_API_KEY") {
        (key, Some("MIMO_API_KEY".into()))
    } else if let Ok(key) = std::env::var("OPENAI_API_KEY") {
        (key, Some("OPENAI_API_KEY".into()))
    } else if !file_key.is_empty() {
        (file_key, Some(path.to_string_lossy().to_string()))
    } else {
        (String::new(), None)
    };

    // Validate provider exists
    get_provider(&provider_id)?;

    Some(ProviderConfig {
        provider: provider_id,
        model,
        api_key,
        api_key_source: key_source,
        protocol,
        url,
        language,
    })
}

/// Require a valid config. Returns error if not configured.
pub fn require_config(path: &Path) -> Result<ProviderConfig, String> {
    let config = load_config(path).ok_or_else(|| {
        "LLM provider not configured. Run `frais config manage` to set up.".to_string()
    })?;
    if !config.is_ready() {
        return Err("LLM provider configuration is incomplete.".to_string());
    }
    Ok(config)
}

/// Save config to TOML file atomically.
pub fn save_config(
    provider_id: &str,
    model: &str,
    api_key: &str,
    protocol: &str,
    url: &str,
    language: &str,
    path: &Path,
) -> Result<(), String> {
    let toml_content = format!(
        "[llm]\nprovider = {provider}\nmodel = {model}\napi_key = {key}\nprotocol = {proto}\nurl = {url}\nlanguage = {lang}\n",
        provider = toml_escape(provider_id),
        model = toml_escape(model),
        key = toml_escape(api_key),
        proto = toml_escape(protocol),
        url = toml_escape(url),
        lang = toml_escape(language),
    );

    // Ensure parent directory
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|e| format!("Cannot create config dir: {e}"))?;
    }

    // Atomic write: write to .tmp then rename
    let tmp_path = path.with_extension("toml.tmp");
    std::fs::write(&tmp_path, toml_content).map_err(|e| format!("Cannot write config: {e}"))?;
    std::fs::rename(&tmp_path, path).map_err(|e| format!("Cannot save config: {e}"))?;

    Ok(())
}

/// Escape a value for TOML basic string.
/// Escapes backslash, double-quote, and all control characters (U+0000–U+001F except tab).
fn toml_escape(value: &str) -> String {
    let escaped: String = value
        .chars()
        .map(|c| match c {
            '\\' => "\\\\".to_string(),
            '"' => "\\\"".to_string(),
            '\x08' => "\\b".to_string(),
            '\x0C' => "\\f".to_string(),
            '\n' => "\\n".to_string(),
            '\r' => "\\r".to_string(),
            '\t' => "\\t".to_string(),
            c if (c as u32) < 0x20 => format!("\\u{:04x}", c as u32),
            c => c.to_string(),
        })
        .collect();
    format!("\"{}\"", escaped)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_load_config_returns_none_for_missing_file() {
        let config = load_config(Path::new("/nonexistent/path/config.toml"));
        assert!(config.is_none());
    }

    #[test]
    fn test_provider_config_is_ready() {
        let config = ProviderConfig {
            provider: "deepseek".into(),
            model: "deepseek-v4-flash".into(),
            api_key: "sk-test".into(),
            api_key_source: Some("config".into()),
            protocol: "openai".into(),
            url: "".into(),
            language: "en".into(),
        };
        assert!(config.is_ready());
    }

    #[test]
    fn test_provider_config_not_ready_without_key() {
        let config = ProviderConfig {
            provider: "deepseek".into(),
            model: "deepseek-v4-flash".into(),
            api_key: "".into(),
            api_key_source: None,
            protocol: "openai".into(),
            url: "".into(),
            language: "en".into(),
        };
        assert!(!config.is_ready());
    }

    #[test]
    #[serial_test::serial]
    fn test_save_and_load_config_round_trip() {
        // Ensure env vars don't pollute this test
        std::env::remove_var("FRAIS_LLM_API_KEY");
        std::env::remove_var("MIMO_API_KEY");
        std::env::remove_var("OPENAI_API_KEY");

        let dir = tempfile::TempDir::new().unwrap();
        let path = dir.path().join("config.toml");

        save_config("deepseek", "deepseek-v4-flash", "sk-test", "openai", "", "en", &path).unwrap();
        let config = load_config(&path).unwrap();

        assert_eq!(config.provider, "deepseek");
        assert_eq!(config.model, "deepseek-v4-flash");
        assert_eq!(config.api_key, "sk-test");
        assert_eq!(config.protocol, "openai");
        assert_eq!(config.language, "en");
    }

    #[test]
    #[serial_test::serial]
    fn test_load_config_env_var_overrides_key() {
        let dir = tempfile::TempDir::new().unwrap();
        let path = dir.path().join("config.toml");

        save_config("deepseek", "deepseek-v4-flash", "file-key", "openai", "", "en", &path).unwrap();
        std::env::set_var("FRAIS_LLM_API_KEY", "env-key-1234");

        let config = load_config(&path).unwrap();
        assert_eq!(config.api_key, "env-key-1234");
        assert_eq!(config.api_key_source, Some("FRAIS_LLM_API_KEY".into()));

        std::env::remove_var("FRAIS_LLM_API_KEY");
    }

    #[test]
    fn test_load_config_returns_none_for_unknown_provider() {
        let dir = tempfile::TempDir::new().unwrap();
        let path = dir.path().join("config.toml");
        let toml = "[llm]\nprovider = \"unknown\"\nmodel = \"test\"\napi_key = \"sk-test\"\n";
        std::fs::write(&path, toml).unwrap();

        let config = load_config(&path);
        assert!(config.is_none());
    }
}
