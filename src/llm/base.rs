// Abstract LLM client trait — matches Python's frais/llm/_base.py.

use crate::store::config_store::ProviderConfig;
use serde::Serialize;
use std::fmt;

/// LLM request error — matches Python's LLMRequestError(RuntimeError).
#[derive(Debug, Clone)]
pub struct LLMRequestError {
    pub message: String,
    pub status_code: Option<u16>,
    pub response_text: String,
}

impl LLMRequestError {
    pub fn new(message: &str) -> Self {
        LLMRequestError {
            message: message.to_string(),
            status_code: None,
            response_text: String::new(),
        }
    }

    pub fn with_status(message: &str, status_code: u16) -> Self {
        LLMRequestError {
            message: message.to_string(),
            status_code: Some(status_code),
            response_text: String::new(),
        }
    }

    pub fn with_response(message: &str, status_code: u16, response_text: &str) -> Self {
        // Truncate body to 300 chars — matches Python's LLMRequestError.from_response().
        let truncated = if response_text.len() > 300 {
            format!(
                "{}...<truncated>",
                response_text.chars().take(300).collect::<String>()
            )
        } else {
            response_text.to_string()
        };
        LLMRequestError {
            message: message.to_string(),
            status_code: Some(status_code),
            response_text: truncated,
        }
    }
}

impl fmt::Display for LLMRequestError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.message)?;
        if let Some(code) = self.status_code {
            write!(f, " (status {code})")?;
        }
        if !self.response_text.is_empty() {
            write!(f, ": {}", self.response_text)?;
        }
        Ok(())
    }
}

impl std::error::Error for LLMRequestError {}

/// Search result from web_search — matches Python's web search result dict.
#[derive(Debug, Clone, Serialize)]
pub struct SearchResult {
    pub title: String,
    pub url: String,
    pub snippet: String,
}

/// Abstract LLM client trait — matches Python's LLMClient ABC.
pub trait LLMClient: Send + Sync {
    /// Send a chat completion request and return response text.
    fn chat(
        &self,
        system: &str,
        user: &str,
        max_tokens: Option<u32>,
        disable_thinking: bool,
    ) -> Result<String, LLMRequestError>;

    /// Close the underlying HTTP client.
    fn close(&self);

    /// Execute a web search. Default returns empty.
    fn web_search(&self, _query: &str) -> Vec<SearchResult> {
        vec![]
    }

    /// Whether this client implementation supports server-side web search.
    /// Override in clients that have a real implementation (e.g. DeepSeek Anthropic).
    fn supports_web_search(&self) -> bool {
        false
    }

    /// Test connection with a minimal request.
    fn test_connection(&self) -> Result<String, LLMRequestError> {
        self.chat("", "Reply with exactly: ok", Some(64), true)
    }

    /// Check if the configured model has thinking support.
    fn model_supports_thinking(&self, config: &ProviderConfig) -> bool {
        config
            .get_provider()
            .map(|p| p.model_supports_thinking(&config.model))
            .unwrap_or(false)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_llm_request_error_display() {
        let err = LLMRequestError::with_response("API error", 500, "Internal Server Error");
        let s = err.to_string();
        assert!(s.contains("API error"));
        assert!(s.contains("500"));
        assert!(s.contains("Internal Server Error"));
    }

    #[test]
    fn test_llm_request_error_truncates_long_body() {
        let long_body = "x".repeat(2000);
        let err = LLMRequestError::with_response("Error", 500, &long_body);
        // Python truncates body to 300 chars
        assert!(err.response_text.len() <= 330); // 300 + "...<truncated>" = 315
        assert!(err.response_text.ends_with("<truncated>"));
    }

    #[test]
    fn test_llm_request_error_handles_empty_body() {
        let err = LLMRequestError::with_response("Empty", 200, "");
        assert_eq!(err.response_text, "");
    }
}
