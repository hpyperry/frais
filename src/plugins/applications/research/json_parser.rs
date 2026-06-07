// JSON parser for LLM outputs — matches Python's research/json_parser.py.
// Key difference from typical Rust: parse failures return empty list/object (with log warning),
// matching Python's _parse_json_list and _parse_json_object exactly.

/// Extract a JSON object or array from LLM output text.
/// Matches Python's _extract_json() exactly.
/// Rust's extract_balanced handles arbitrary nesting depth — strictly better than Python's regex.
pub fn extract_json(text: &str) -> String {
    let text = text.trim();

    // Try to extract from markdown code fence
    if let Some(inner) = extract_fenced_json(text) {
        return inner;
    }

    // Find first { or [ — extract_balanced handles arbitrary nesting
    if let Some(result) = extract_balanced(text, '{', '}') {
        return result;
    }
    if let Some(result) = extract_balanced(text, '[', ']') {
        return result;
    }

    text.to_string()
}

fn extract_fenced_json(text: &str) -> Option<String> {
    let text = text.trim();
    // Match ```json ... ``` or ``` ... ```
    if text.starts_with("```") {
        let without_fence = text
            .strip_prefix("```")
            .and_then(|s| s.strip_prefix("json"))
            .unwrap_or_else(|| text.strip_prefix("```").unwrap_or(text));
        if let Some(end) = without_fence.rfind("```") {
            return Some(without_fence[..end].trim().to_string());
        }
    }
    None
}

fn extract_balanced(text: &str, open: char, close: char) -> Option<String> {
    let start = text.find(open)?;
    let mut depth = 0;
    let mut in_string = false;
    let mut escaped = false;
    let chars: Vec<char> = text[start..].chars().collect();
    for (i, c) in chars.iter().enumerate() {
        if in_string {
            if escaped {
                escaped = false;
            } else if *c == '\\' {
                escaped = true;
            } else if *c == '"' {
                in_string = false;
            }
        } else if *c == '"' {
            in_string = true;
        } else if *c == open {
            depth += 1;
        } else if *c == close {
            depth -= 1;
            if depth == 0 {
                return Some(chars[..=i].iter().collect());
            }
        }
    }
    None
}

/// Parse a JSON list of strings from LLM output.
/// Matches Python's _parse_json_list: returns empty list on failure (with log warning).
pub fn parse_json_list(text: &str) -> Vec<String> {
    let json = extract_json(text);
    match serde_json::from_str::<serde_json::Value>(&json) {
        Ok(value) => match ensure_list(&value) {
            Ok(list) => list,
            Err(_) => {
                log::warn!("failed to parse JSON list from: {}", &text.chars().take(200).collect::<String>());
                vec![]
            }
        },
        Err(_) => {
            log::warn!("failed to parse JSON list from: {}", &text.chars().take(200).collect::<String>());
            vec![]
        }
    }
}

/// Parse a JSON object from LLM output.
/// Matches Python's _parse_json_object: returns empty object on failure (with log warning).
pub fn parse_json_object(text: &str) -> serde_json::Value {
    let json = extract_json(text);
    match serde_json::from_str::<serde_json::Value>(&json) {
        Ok(v @ serde_json::Value::Object(_)) => v,
        Ok(_) => {
            log::warn!("failed to parse JSON object from: {}", &text.chars().take(200).collect::<String>());
            serde_json::json!({})
        }
        Err(_) => {
            log::warn!("failed to parse JSON object from: {}", &text.chars().take(200).collect::<String>());
            serde_json::json!({})
        }
    }
}

/// Ensure a JSON value is a list of strings.
/// Matches Python's _ensure_list exactly.
pub fn ensure_list(value: &serde_json::Value) -> Result<Vec<String>, String> {
    match value {
        serde_json::Value::Array(arr) => Ok(arr
            .iter()
            .filter_map(|v| v.as_str().map(|s| s.to_string()))
            .filter(|s| !s.is_empty())
            .collect()),
        serde_json::Value::String(s) if !s.is_empty() => Ok(vec![s.clone()]),
        _ => Err("Expected a list".into()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_extract_json_from_markdown_fence() {
        let text = "```json\n[\"a\", \"b\"]\n```";
        let result = extract_json(text);
        assert_eq!(result, "[\"a\", \"b\"]");
    }

    #[test]
    fn test_extract_json_from_markdown_fence_no_lang() {
        let text = "```\n{\"key\": \"val\"}\n```";
        let result = extract_json(text);
        assert_eq!(result, "{\"key\": \"val\"}");
    }

    #[test]
    fn test_extract_json_raw_array() {
        let text = "[\"query1\", \"query2\"]";
        let result = extract_json(text);
        assert!(result.starts_with("["));
    }

    #[test]
    fn test_parse_json_list_success() {
        let result = parse_json_list("[\"a\", \"b\", \"c\"]");
        assert_eq!(result.len(), 3);
    }

    #[test]
    fn test_parse_json_list_empty_on_failure() {
        // Matches Python: _parse_json_list returns [] on parse failure
        let result = parse_json_list("not json");
        assert!(result.is_empty());
    }

    #[test]
    fn test_parse_json_object_empty_on_failure() {
        // Matches Python: _parse_json_object returns {} on parse failure
        let result = parse_json_object("not json");
        assert!(result.as_object().unwrap().is_empty());
    }

    #[test]
    fn test_ensure_list_from_array() {
        let val = serde_json::json!(["a", "b"]);
        let result = ensure_list(&val).unwrap();
        assert_eq!(result.len(), 2);
    }

    #[test]
    fn test_ensure_list_from_string() {
        let val = serde_json::json!("single");
        let result = ensure_list(&val).unwrap();
        assert_eq!(result, vec!["single"]);
    }
}
