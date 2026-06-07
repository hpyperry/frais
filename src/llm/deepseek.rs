// DeepSeek-specific LLM clients — matches Python's frais/llm/_deepseek.py.
// Two protocol implementations: OpenAI and Anthropic Messages API.

use crate::llm::base::{LLMClient, LLMRequestError, SearchResult};
use crate::llm::openai_compat::OpenAICompatibleClient;
use crate::store::config_store::ProviderConfig;

// ============================================================================
// DeepSeek OpenAI Protocol Client
// ============================================================================

/// DeepSeek client using OpenAI protocol with thinking support.
pub struct DeepSeekOpenAIClient {
    inner: OpenAICompatibleClient,
}

impl DeepSeekOpenAIClient {
    pub fn new(config: &ProviderConfig) -> Result<Self, String> {
        Ok(DeepSeekOpenAIClient {
            inner: OpenAICompatibleClient::new(config)?,
        })
    }

    pub fn new_boxed(config: &ProviderConfig) -> Result<Box<dyn LLMClient>, String> {
        Ok(Box::new(Self::new(config)?))
    }
}

impl LLMClient for DeepSeekOpenAIClient {
    fn chat(
        &self,
        system: &str,
        user: &str,
        max_tokens: Option<u32>,
        disable_thinking: bool,
    ) -> Result<String, LLMRequestError> {
        let messages = self.inner.build_messages(system, user);
        let mut payload = self.inner.build_payload(&messages, max_tokens);

        // DeepSeek OpenAI protocol: inject thinking via extra_body
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

    fn web_search(&self, _query: &str) -> Vec<SearchResult> {
        // DeepSeek OpenAI protocol does NOT support server-side web search
        vec![]
    }
}

// ============================================================================
// DeepSeek Anthropic Protocol Client
// ============================================================================

/// DeepSeek client using Anthropic Messages API protocol.
/// Supports server-side web_search via Anthropic tool calling.
pub struct DeepSeekAnthropicClient {
    config: ProviderConfig,
    client: reqwest::blocking::Client,
}

impl DeepSeekAnthropicClient {
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

        Ok(DeepSeekAnthropicClient {
            config: config.clone(),
            client,
        })
    }

    pub fn new_boxed(config: &ProviderConfig) -> Result<Box<dyn LLMClient>, String> {
        Ok(Box::new(Self::new(config)?))
    }

    fn base_url(&self) -> String {
        if self.config.url.is_empty() {
            self.config
                .get_provider()
                .and_then(|p| p.get_protocol_url("anthropic").cloned())
                .unwrap_or_else(|| "https://api.deepseek.com/anthropic".into())
        } else {
            self.config.url.clone()
        }
    }
}

impl LLMClient for DeepSeekAnthropicClient {
    fn chat(
        &self,
        system: &str,
        user: &str,
        max_tokens: Option<u32>,
        disable_thinking: bool,
    ) -> Result<String, LLMRequestError> {
        let max_tokens = max_tokens.unwrap_or(4096);

        let mut payload = serde_json::json!({
            "model": self.config.model,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "user", "content": user}
            ]
        });

        // Anthropic protocol: system is a top-level parameter, not a message
        if !system.is_empty() {
            payload["system"] = serde_json::json!(system);
        }

        // Thinking control
        if self.model_supports_thinking(&self.config) {
            if disable_thinking {
                payload["thinking"] = serde_json::json!({"type": "disabled"});
            } else {
                payload["thinking"] = serde_json::json!({
                    "type": "enabled",
                    "budget_tokens": 1024
                });
            }
        }

        let url = format!("{}/v1/messages", self.base_url());

        let response = self
            .client
            .post(&url)
            .header("x-api-key", &self.config.api_key)
            .header("anthropic-version", "2023-06-01")
            .header("Content-Type", "application/json")
            .json(&payload)
            .send()
            .map_err(|e| {
                if e.is_timeout() || e.is_connect() {
                    LLMRequestError::new(&format!("Connection error: {e}"))
                } else {
                    LLMRequestError::new(&format!("Request error: {e}"))
                }
            })?;

        let status = response.status().as_u16();
        let response_text = response.text().unwrap_or_default();

        if status != 200 {
            return Err(LLMRequestError::with_response(
                &format!("Anthropic API returned status {status}"),
                status,
                &response_text,
            ));
        }

        let body: serde_json::Value =
            serde_json::from_str(&response_text).map_err(|e| {
                LLMRequestError::new(&format!("Cannot parse response: {e}"))
            })?;

        // Extract text from content blocks
        let content = body["content"]
            .as_array()
            .and_then(|blocks| {
                blocks
                    .iter()
                    .filter_map(|b| b["text"].as_str())
                    .collect::<Vec<_>>()
                    .join("")
                    .into()
            })
            .filter(|s: &String| !s.is_empty());

        match content {
            Some(text) => Ok(text),
            None => Err(LLMRequestError::new("Empty content in Anthropic API response")),
        }
    }

    fn close(&self) {
        // reqwest::blocking::Client closes when dropped
    }

    fn web_search(&self, query: &str) -> Vec<SearchResult> {
        // DeepSeek Anthropic protocol supports server-side web_search via the
        // web_search_20250305 tool. Matches Python's DeepSeekAnthropicClient.web_search() exactly.
        if query.trim().is_empty() {
            return vec![];
        }

        log::debug!("anthropic web_search query={}", query);

        let payload = serde_json::json!({
            "model": self.config.model,
            "max_tokens": 4096,
            "system": "You are a web search assistant. Use the web_search tool to find relevant results.",
            "messages": [
                {"role": "user", "content": format!("Search the web for: {}", query)}
            ],
            "tools": [
                {
                    "type": "web_search_20250305",
                    "name": "web_search",
                    "max_uses": 4
                }
            ],
            "thinking": {"type": "disabled"}
        });

        let url = format!("{}/v1/messages", self.base_url());

        let response = match self
            .client
            .post(&url)
            .header("x-api-key", &self.config.api_key)
            .header("anthropic-version", "2023-06-01")
            .header("Content-Type", "application/json")
            .json(&payload)
            .send()
        {
            Ok(r) => r,
            Err(e) => {
                log::warn!("anthropic web_search failed for {}: {}", query, e);
                return vec![];
            }
        };

        let status = response.status().as_u16();
        if status != 200 {
            let body = response.text().unwrap_or_default();
            log::warn!(
                "anthropic web_search returned status {} for {}: {}",
                status,
                query,
                &body.chars().take(300).collect::<String>()
            );
            return vec![];
        }

        let body: serde_json::Value = match response.json() {
            Ok(v) => v,
            Err(e) => {
                log::warn!("anthropic web_search parse failed for {}: {}", query, e);
                return vec![];
            }
        };

        // Check for API-level errors in the response
        if let Some(err_type) = body["type"].as_str() {
            if err_type == "error" {
                let msg = body["error"]["message"]
                    .as_str()
                    .unwrap_or("unknown error");
                log::warn!("anthropic web_search API error for {}: {}", query, msg);
                return vec![];
            }
        }

        let mut results = Vec::new();
        if let Some(blocks) = body["content"].as_array() {
            for block in blocks {
                if block["type"].as_str() == Some("web_search_tool_result") {
                    if let Some(items) = block["content"].as_array() {
                        for item in items {
                            if let (Some(url), Some(title)) = (
                                item["url"].as_str(),
                                item["title"].as_str(),
                            ) {
                                if !url.is_empty() {
                                    results.push(SearchResult {
                                        title: title.to_string(),
                                        url: url.to_string(),
                                        snippet: String::new(),
                                    });
                                }
                            }
                        }
                    }
                }
            }
        }

        if results.is_empty() {
            log::info!(
                "anthropic web_search returned no results for {}, will fallback to DDGS",
                query
            );
        } else {
            log::debug!(
                "anthropic web_search found {} results query={}",
                results.len(),
                query
            );
        }

        results
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
        }
    }

    #[test]
    fn test_deepseek_openai_new() {
        let config = test_config();
        let client = DeepSeekOpenAIClient::new(&config);
        assert!(client.is_ok());
    }

    #[test]
    fn test_deepseek_anthropic_new() {
        let config = test_config();
        let client = DeepSeekAnthropicClient::new(&config);
        assert!(client.is_ok());
    }

    #[test]
    fn test_deepseek_openai_web_search_returns_empty() {
        let config = test_config();
        let client = DeepSeekOpenAIClient::new(&config).unwrap();
        let results = client.web_search("test query");
        assert!(results.is_empty());
    }

    #[test]
    fn test_deepseek_anthropic_config_not_ready() {
        let config = ProviderConfig {
            provider: "deepseek".into(),
            model: "deepseek-v4-flash".into(),
            api_key: "".into(),
            api_key_source: None,
            protocol: "anthropic".into(),
            url: "".into(),
        };
        let result = DeepSeekAnthropicClient::new(&config);
        assert!(result.is_err());
    }
}
