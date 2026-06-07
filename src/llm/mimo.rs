// MiMo (Xiaomi) LLM client — matches Python's frais/llm/_mimo.py.
// Uses max_completion_tokens instead of max_tokens, with proprietary web_search tool.

use crate::llm::base::{LLMClient, LLMRequestError, SearchResult};
use crate::llm::openai_compat::OpenAICompatibleClient;
use crate::store::config_store::ProviderConfig;

pub struct MiMoClient {
    inner: OpenAICompatibleClient,
}

impl MiMoClient {
    pub fn new(config: &ProviderConfig) -> Result<Self, String> {
        Ok(MiMoClient {
            inner: OpenAICompatibleClient::new(config)?,
        })
    }

    pub fn new_boxed(config: &ProviderConfig) -> Result<Box<dyn LLMClient>, String> {
        Ok(Box::new(Self::new(config)?))
    }
}

impl LLMClient for MiMoClient {
    fn chat(
        &self,
        system: &str,
        user: &str,
        max_tokens: Option<u32>,
        disable_thinking: bool,
    ) -> Result<String, LLMRequestError> {
        let messages = self.inner.build_messages(system, user);
        let mut payload = self.inner.build_payload(&messages, max_tokens);

        // MiMo uses max_completion_tokens, not max_tokens
        payload.as_object_mut().map(|obj| {
            obj.remove("max_tokens");
        });
        if let Some(mt) = max_tokens {
            if mt > 0 {
                payload["max_completion_tokens"] = serde_json::json!(mt);
            }
        }

        // Thinking control
        if self.model_supports_thinking(&self.inner.config) {
            let thinking_value = if disable_thinking {
                serde_json::json!({"type": "disabled"})
            } else {
                serde_json::json!({"type": "enabled"})
            };
            payload["extra_body"] = serde_json::json!({"thinking": thinking_value});
        }

        self.inner.create(&payload)
    }

    fn close(&self) {
        self.inner.close();
    }

    fn web_search(&self, query: &str) -> Vec<SearchResult> {
        // MiMo supports server-side web search via OpenAI protocol with url_citation
        // For now return empty; will be fully implemented in Phase 7
        let _ = query;
        vec![]
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn test_config() -> ProviderConfig {
        ProviderConfig {
            provider: "mimo".into(),
            model: "mimo-v2.5-pro".into(),
            api_key: "sk-test".into(),
            api_key_source: Some("config".into()),
            protocol: "openai".into(),
            url: "".into(),
            language: "en".into(),
        }
    }

    #[test]
    fn test_mimo_new() {
        let config = test_config();
        let client = MiMoClient::new(&config);
        assert!(client.is_ok());
    }

    #[test]
    fn test_mimo_not_ready() {
        let config = ProviderConfig {
            provider: "mimo".into(),
            model: "".into(),
            api_key: "".into(),
            api_key_source: None,
            protocol: "openai".into(),
            url: "".into(),
            language: "en".into(),
        };
        let result = MiMoClient::new(&config);
        assert!(result.is_err());
    }
}
