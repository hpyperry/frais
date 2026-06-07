// OpenAI-compatible LLM client — matches Python's frais/llm/_openai_compatible.py.
// Uses reqwest::blocking for HTTP (matches Python's sync httpx pattern).

use crate::llm::base::{LLMClient, LLMRequestError};
use crate::store::config_store::ProviderConfig;

/// OpenAI-compatible client using the /v1/chat/completions endpoint.
pub struct OpenAICompatibleClient {
    pub(crate) config: ProviderConfig,
    pub(crate) client: reqwest::blocking::Client,
}

impl OpenAICompatibleClient {
    /// Create a new OpenAI-compatible client.
    pub fn new(config: &ProviderConfig) -> Result<Self, String> {
        if !config.is_ready() {
            return Err("Provider configuration is not ready".into());
        }

        let timeout = std::time::Duration::from_secs(300);
        let client = reqwest::blocking::Client::builder()
            .timeout(timeout)
            .user_agent("frais/0.1.0")
            .build()
            .map_err(|e| format!("Cannot create HTTP client: {e}"))?;

        Ok(OpenAICompatibleClient {
            config: config.clone(),
            client,
        })
    }

    /// Boxed constructor for the factory registry.
    pub fn new_boxed(config: &ProviderConfig) -> Result<Box<dyn LLMClient>, String> {
        Ok(Box::new(Self::new(config)?))
    }

    /// Build chat messages from system and user prompts.
    pub(crate) fn build_messages(&self, system: &str, user: &str) -> Vec<serde_json::Value> {
        let mut messages = Vec::new();
        if !system.is_empty() {
            messages.push(serde_json::json!({
                "role": "system",
                "content": system
            }));
        }
        messages.push(serde_json::json!({
            "role": "user",
            "content": user
        }));
        messages
    }

    /// Build the full API payload.
    pub(crate) fn build_payload(
        &self,
        messages: &[serde_json::Value],
        max_tokens: Option<u32>,
    ) -> serde_json::Value {
        let mut payload = serde_json::json!({
            "model": self.config.model,
            "messages": messages,
            "temperature": 0.2,
        });

        if let Some(mt) = max_tokens {
            payload["max_tokens"] = serde_json::json!(mt);
        }

        payload
    }

    /// Apply thinking configuration. Default: no-op. Subclasses override.
    fn apply_thinking(&self, _thinking_enabled: bool) -> Option<serde_json::Value> {
        None
    }

    /// Execute the API call.
    pub(crate) fn create(&self, payload: &serde_json::Value) -> Result<String, LLMRequestError> {
        let base = if self.config.url.is_empty() {
            self.config
                .get_provider()
                .and_then(|p| p.get_protocol_url("openai").cloned())
                .unwrap_or_else(|| "https://api.deepseek.com".into())
        } else {
            self.config.url.clone()
        };
        // Avoid double /v1 when user configures e.g. url = "http://localhost:8000/v1"
        // Strip trailing slash first to handle "/v1/" (common with OpenWebUI/LiteLLM proxies).
        let base = base.trim_end_matches('/');
        let url = if base.ends_with("/v1") {
            format!("{base}/chat/completions")
        } else {
            format!("{base}/v1/chat/completions")
        };

        let response = self
            .client
            .post(&url)
            .header("Authorization", format!("Bearer {}", self.config.api_key))
            .header("Content-Type", "application/json")
            .json(payload)
            .send()
            .map_err(|e| {
                if e.is_timeout() || e.is_connect() {
                    LLMRequestError::new(&format!("Connection error: {e}"))
                } else {
                    LLMRequestError::new(&format!("Request error: {e}"))
                }
            })?;

        let status = response.status().as_u16();
        let response_text = match response.text() {
            Ok(t) => t,
            Err(e) => {
                return Err(LLMRequestError::new(&format!(
                    "Failed to read response body (status {status}): {e}"
                )));
            }
        };

        if status != 200 {
            return Err(LLMRequestError::with_response(
                &format!("API returned status {status}"),
                status,
                &response_text,
            ));
        }

        let body: serde_json::Value =
            serde_json::from_str(&response_text).map_err(|e| {
                LLMRequestError::new(&format!("Cannot parse response: {e}"))
            })?;

        let content = body["choices"][0]["message"]["content"]
            .as_str()
            .unwrap_or("");

        if content.is_empty() {
            return Err(LLMRequestError::new("Empty content in API response"));
        }

        Ok(content.to_string())
    }
}

impl LLMClient for OpenAICompatibleClient {
    fn chat(
        &self,
        system: &str,
        user: &str,
        max_tokens: Option<u32>,
        disable_thinking: bool,
    ) -> Result<String, LLMRequestError> {
        let messages = self.build_messages(system, user);
        let mut payload = self.build_payload(&messages, max_tokens);

        // Apply thinking if model supports it
        if self.model_supports_thinking(&self.config) {
            if let Some(thinking_extra) = self.apply_thinking(!disable_thinking) {
                payload["extra_body"] = thinking_extra;
            }
        }

        self.create(&payload)
    }

    fn close(&self) {
        // reqwest::blocking::Client closes when dropped
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    

    fn test_config() -> ProviderConfig {
        ProviderConfig {
            provider: "deepseek".into(),
            model: "deepseek-v4-flash".into(),
            api_key: "sk-test".into(),
            api_key_source: Some("config".into()),
            protocol: "openai".into(),
            url: "".into(),
            language: "en".into(),
        }
    }

    #[test]
    fn test_new_raises_when_config_not_ready() {
        let config = ProviderConfig {
            provider: "deepseek".into(),
            model: "deepseek-v4-flash".into(),
            api_key: "".into(),
            api_key_source: None,
            protocol: "openai".into(),
            url: "".into(),
            language: "en".into(),
        };
        let result = OpenAICompatibleClient::new(&config);
        assert!(result.is_err());
    }

    #[test]
    fn test_new_succeeds_with_ready_config() {
        let config = test_config();
        let result = OpenAICompatibleClient::new(&config);
        assert!(result.is_ok());
    }

    #[test]
    fn test_build_messages_excludes_empty_system() {
        let config = test_config();
        let client = OpenAICompatibleClient::new(&config).unwrap();
        let msgs = client.build_messages("", "hello");
        assert_eq!(msgs.len(), 1);
        assert_eq!(msgs[0]["role"], "user");
    }

    #[test]
    fn test_build_messages_includes_system_when_present() {
        let config = test_config();
        let client = OpenAICompatibleClient::new(&config).unwrap();
        let msgs = client.build_messages("You are helpful", "hello");
        assert_eq!(msgs.len(), 2);
        assert_eq!(msgs[0]["role"], "system");
    }
}
