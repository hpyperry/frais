// Provider definitions — matches Python's frais/providers.py.
// Static registry of LLM providers and their models.

use serde::{Deserialize, Serialize};

/// Model information — matches Python's ModelInfo dataclass.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ModelInfo {
    pub id: String,
    pub name: String,
    #[serde(default)]
    pub supports_thinking: bool,
}

/// Provider definition — matches Python's Provider dataclass.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct Provider {
    pub id: String,
    pub name: String,
    pub models: Vec<ModelInfo>,
    pub protocols: Vec<String>,
    pub web_search_protocols: Vec<String>,
    pub protocol_urls: std::collections::BTreeMap<String, String>,
}

impl Provider {
    /// Find a model by ID within this provider.
    pub fn find_model(&self, model_id: &str) -> Option<&ModelInfo> {
        self.models.iter().find(|m| m.id == model_id)
    }

    /// Get the URL for a given protocol.
    pub fn get_protocol_url(&self, protocol: &str) -> Option<&String> {
        self.protocol_urls.get(protocol)
    }

    /// Check if this provider supports thinking for a given model.
    pub fn model_supports_thinking(&self, model_id: &str) -> bool {
        self.find_model(model_id)
            .map(|m| m.supports_thinking)
            .unwrap_or(false)
    }
}

/// Built-in providers — matches Python's PROVIDERS list.
/// Cached in a OnceLock to avoid re-allocating on every call.
pub fn builtin_providers() -> &'static [Provider] {
    use std::sync::OnceLock;
    static PROVIDERS: OnceLock<Vec<Provider>> = OnceLock::new();
    PROVIDERS.get_or_init(|| vec![
        Provider {
            id: "deepseek".into(),
            name: "DeepSeek".into(),
            models: vec![
                ModelInfo {
                    id: "deepseek-v4-flash".into(),
                    name: "DeepSeek V4 Flash".into(),
                    supports_thinking: true,
                },
                ModelInfo {
                    id: "deepseek-v4-pro".into(),
                    name: "DeepSeek V4 Pro".into(),
                    supports_thinking: true,
                },
                ModelInfo {
                    id: "deepseek-chat".into(),
                    name: "DeepSeek Chat (deprecated)".into(),
                    supports_thinking: false,
                },
            ],
            protocols: vec!["openai".into(), "anthropic".into()],
            web_search_protocols: vec!["anthropic".into()],
            protocol_urls: {
                let mut m = std::collections::BTreeMap::new();
                m.insert("openai".into(), "https://api.deepseek.com".into());
                m.insert("anthropic".into(), "https://api.deepseek.com/anthropic".into());
                m
            },
        },
        Provider {
            id: "mimo".into(),
            name: "Xiaomi MiMo".into(),
            models: vec![
                ModelInfo {
                    id: "mimo-v2.5-pro".into(),
                    name: "MiMo V2.5 Pro".into(),
                    supports_thinking: true,
                },
                ModelInfo {
                    id: "mimo-v2-flash".into(),
                    name: "MiMo V2 Flash".into(),
                    supports_thinking: false,
                },
            ],
            protocols: vec!["openai".into()],
            web_search_protocols: vec!["openai".into()],
            protocol_urls: {
                let mut m = std::collections::BTreeMap::new();
                m.insert("openai".into(), "https://api.xiaomimimo.com/v1".into());
                m
            },
        },
    ])
}

/// Look up a provider by ID.
pub fn get_provider(provider_id: &str) -> Option<Provider> {
    builtin_providers().iter().find(|p| p.id == provider_id).cloned()
}

/// Get the URL for a provider and protocol.
pub fn get_protocol_url(provider: &Provider, protocol: &str) -> Option<String> {
    provider.get_protocol_url(protocol).cloned()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_get_provider_returns_some_for_deepseek() {
        let p = get_provider("deepseek");
        assert!(p.is_some());
        let p = p.unwrap();
        assert_eq!(p.name, "DeepSeek");
        assert!(!p.models.is_empty());
    }

    #[test]
    fn test_get_provider_returns_none_for_unknown() {
        let p = get_provider("nonexistent");
        assert!(p.is_none());
    }

    #[test]
    fn test_get_provider_returns_some_for_mimo() {
        let p = get_provider("mimo");
        assert!(p.is_some());
    }

    #[test]
    fn test_all_providers_have_models() {
        for p in builtin_providers() {
            assert!(!p.models.is_empty(), "Provider {} has no models", p.id);
        }
    }

    #[test]
    fn test_all_providers_have_protocol_urls() {
        for p in builtin_providers() {
            for proto in &p.protocols {
                assert!(
                    p.protocol_urls.contains_key(proto),
                    "Provider {} missing URL for protocol {}",
                    p.id,
                    proto
                );
            }
        }
    }

    #[test]
    fn test_protocol_url_resolution() {
        let deepseek = get_provider("deepseek").unwrap();
        let url = get_protocol_url(&deepseek, "openai");
        assert_eq!(url, Some("https://api.deepseek.com".into()));
    }

    #[test]
    fn test_find_model() {
        let deepseek = get_provider("deepseek").unwrap();
        let model = deepseek.find_model("deepseek-v4-pro");
        assert!(model.is_some());
        assert!(model.unwrap().supports_thinking);
    }

    #[test]
    fn test_model_supports_thinking_flag() {
        let deepseek = get_provider("deepseek").unwrap();
        assert!(deepseek.model_supports_thinking("deepseek-v4-flash"));
        assert!(!deepseek.model_supports_thinking("deepseek-chat"));
    }
}
