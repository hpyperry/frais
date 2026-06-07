// LLM client layer module — matches Python's frais/llm/ package.
pub mod base;
pub mod deepseek;
pub mod mimo;
pub mod openai_compat;

use crate::store::config_store::ProviderConfig;
use base::LLMClient;
use std::collections::HashMap;

/// Client factory registry — matches Python's _CLIENT_MAP.
type ClientFactory = fn(&ProviderConfig) -> Result<Box<dyn LLMClient>, String>;

/// Get a client factory for a (provider_id, protocol) pair.
fn client_map() -> &'static HashMap<(&'static str, &'static str), ClientFactory> {
    use once_cell::sync::Lazy;
    static MAP: Lazy<HashMap<(&'static str, &'static str), ClientFactory>> = Lazy::new(|| {
        let mut m = HashMap::new();
        m.insert(
            ("deepseek", "openai"),
            deepseek::DeepSeekOpenAIClient::new_boxed as ClientFactory,
        );
        m.insert(
            ("deepseek", "anthropic"),
            deepseek::DeepSeekAnthropicClient::new_boxed as ClientFactory,
        );
        m.insert(
            ("mimo", "openai"),
            mimo::MiMoClient::new_boxed as ClientFactory,
        );
        m
    });
    &MAP
}

/// Create an LLM client from provider config — matches Python's get_client().
pub fn get_client(config: &ProviderConfig, protocol: Option<&str>) -> Result<Box<dyn LLMClient>, String> {
    let protocol = protocol.unwrap_or(&config.protocol);

    // Validate protocol is supported by the provider
    let provider = config
        .get_provider()
        .ok_or_else(|| format!("Unknown provider: {}", config.provider))?;

    if !provider.protocols.iter().any(|p| p == protocol) {
        return Err(format!(
            "Protocol '{}' not supported by provider '{}'",
            protocol, config.provider
        ));
    }

    let factory = client_map()
        .get(&(config.provider.as_str(), protocol))
        .ok_or_else(|| {
            format!(
                "No client for provider '{}' with protocol '{}'",
                config.provider, protocol
            )
        })?;

    factory(config)
}

#[cfg(test)]
mod tests {
    use super::*;
    

    fn test_config(provider_id: &str, key: &str) -> ProviderConfig {
        ProviderConfig {
            provider: provider_id.into(),
            model: "test-model".into(),
            api_key: key.into(),
            api_key_source: Some("config".into()),
            protocol: "openai".into(),
            url: "".into(),
        }
    }

    #[test]
    fn test_get_client_returns_deepseek_openai() {
        let config = test_config("deepseek", "sk-test");
        let client = get_client(&config, Some("openai"));
        assert!(client.is_ok());
    }

    #[test]
    fn test_get_client_returns_deepseek_anthropic() {
        let config = test_config("deepseek", "sk-test");
        let client = get_client(&config, Some("anthropic"));
        assert!(client.is_ok());
    }

    #[test]
    fn test_get_client_unknown_pair_raises() {
        let config = test_config("deepseek", "sk-test");
        let client = get_client(&config, Some("grpc"));
        assert!(client.is_err());
    }
}
