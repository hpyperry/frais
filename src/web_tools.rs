// Web tools — matches Python's frais/web_tools.py.
use crate::llm::base::{LLMClient, SearchResult};
use regex::Regex;
use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};

const SEARCH_MAX_RESULTS: usize = 5;
const FETCH_MAX_CHARS: usize = 5000;

use once_cell::sync::Lazy;
static GITHUB_REPO_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"github\.com/([^/]+/[^/]+?)(?:\.git)?(?:/|$)").unwrap());

// Track DDGS failures to short-circuit after repeated failures.
static DDGS_FAILURE_COUNT: AtomicUsize = AtomicUsize::new(0);
static DDGS_DISABLED: AtomicBool = AtomicBool::new(false);
const DDGS_MAX_CONSECUTIVE_FAILURES: usize = 3;

// Cached HTTP clients — matches Python's @cache on _get_ddgs() and _get_fetch_client().
use std::sync::OnceLock;

fn get_ddgs_client() -> Option<&'static reqwest::blocking::Client> {
    static CLIENT: OnceLock<Option<reqwest::blocking::Client>> = OnceLock::new();
    CLIENT
        .get_or_init(|| {
            reqwest::blocking::Client::builder()
                .connect_timeout(std::time::Duration::from_secs(5))
                .timeout(std::time::Duration::from_secs(8))
                .user_agent(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) \
                     AppleWebKit/537.36 (KHTML, like Gecko) \
                     Chrome/148.0.0.0 Safari/537.36",
                )
                .build()
                .ok()
        })
        .as_ref()
}

fn get_fetch_client() -> Option<&'static reqwest::blocking::Client> {
    static CLIENT: OnceLock<Option<reqwest::blocking::Client>> = OnceLock::new();
    CLIENT
        .get_or_init(|| {
            reqwest::blocking::Client::builder()
                .user_agent(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) \
                     AppleWebKit/537.36 (KHTML, like Gecko) \
                     Chrome/148.0.0.0 Safari/537.36",
                )
                .timeout(std::time::Duration::from_secs(15))
                .build()
                .ok()
        })
        .as_ref()
}

/// Web search via DuckDuckGo — matches Python's web_search() which uses DDGS().text().
/// Short-circuits after repeated connection failures to avoid wasting time on blocked endpoints.
pub fn web_search(query: &str) -> Vec<SearchResult> {
    // Short-circuit if DDGS is disabled due to repeated failures
    if DDGS_DISABLED.load(Ordering::Relaxed) {
        log::debug!("web_search skipped (DDGS disabled): query={}", query);
        return vec![];
    }

    log::debug!("web_search query={}", query);
    let client = match get_ddgs_client() {
        Some(c) => c,
        None => {
            log::warn!("web_search skipped: failed to build DDGS HTTP client");
            return vec![];
        }
    };

    let url = format!(
        "https://html.duckduckgo.com/html/?q={}",
        urlencoding(query)
    );

    let response = match client.get(&url).send() {
        Ok(r) => r,
        Err(e) => {
            log::warn!("web_search failed: {}", e);
            let failures = DDGS_FAILURE_COUNT.fetch_add(1, Ordering::SeqCst) + 1;
            if failures >= DDGS_MAX_CONSECUTIVE_FAILURES {
                DDGS_DISABLED.store(true, Ordering::SeqCst);
                log::warn!(
                    "DDGS disabled after {} consecutive failures — will use provider search only",
                    failures
                );
            }
            return vec![];
        }
    };

    let html = match response.text() {
        Ok(t) => {
            // Reset failure counter on successful connection
            DDGS_FAILURE_COUNT.store(0, Ordering::SeqCst);
            DDGS_DISABLED.store(false, Ordering::SeqCst);
            t
        }
        Err(e) => {
            log::warn!("web_search failed to read response: {}", e);
            return vec![];
        }
    };

    let results = parse_ddg_results(&html);
    log::debug!("web_search found {} results", results.len());
    log::debug!(
        "web_search results={}",
        serde_json::to_string(&results).unwrap_or_default()
    );
    results
}

/// Proper URL encoding matching Python's urllib.parse.quote().
fn urlencoding(s: &str) -> String {
    // Use percent-encoding for proper URL encoding
    // Keep alphanumeric, and the special chars: + - . _ ~
    // Everything else gets percent-encoded
    s.chars()
        .map(|c| {
            if c.is_ascii_alphanumeric() || "+-._~".contains(c) {
                c.to_string()
            } else if c == ' ' {
                "+".to_string()
            } else {
                let mut buf = [0u8; 4];
                let encoded = c.encode_utf8(&mut buf);
                encoded
                    .bytes()
                    .map(|b| format!("%{:02X}", b))
                    .collect::<String>()
            }
        })
        .collect()
}

fn parse_ddg_results(html: &str) -> Vec<SearchResult> {
    use scraper::{Html, Selector};

    let document = Html::parse_document(html);
    let result_sel = match Selector::parse(".result") {
        Ok(s) => s,
        Err(_) => return vec![],
    };
    let title_sel = match Selector::parse(".result__title") {
        Ok(s) => s,
        Err(_) => return vec![],
    };
    let snippet_sel = match Selector::parse(".result__snippet") {
        Ok(s) => s,
        Err(_) => return vec![],
    };
    let link_sel = match Selector::parse(".result__url") {
        Ok(s) => s,
        Err(_) => return vec![],
    };

    let mut results = Vec::new();
    for result in document.select(&result_sel).take(SEARCH_MAX_RESULTS) {
        let title = result
            .select(&title_sel)
            .next()
            .map(|t| t.text().collect::<String>().trim().to_string())
            .unwrap_or_default();
        let snippet = result
            .select(&snippet_sel)
            .next()
            .map(|s| s.text().collect::<String>().trim().to_string())
            .unwrap_or_default();
        let url = result
            .select(&link_sel)
            .next()
            .and_then(|u| u.value().attr("href"))
            .map(|href| href.trim().to_string())
            .unwrap_or_default();

        if !title.is_empty() && !url.is_empty() {
            results.push(SearchResult { title, url, snippet });
        }
    }
    results
}

/// Search strategy: try provider web_search first, fall back to DDGS.
/// Matches Python's web_search_strategy() — includes try/except and logging.
pub fn web_search_strategy(llm: &dyn LLMClient, query: &str) -> Vec<SearchResult> {
    // Try provider web_search first
    let results = llm.web_search(query);
    if !results.is_empty() {
        log::debug!(
            "web_search using provider backend, query={} results={}",
            query,
            results.len()
        );
        return results;
    }
    // If DDGS is already disabled, skip the fallback
    if DDGS_DISABLED.load(Ordering::Relaxed) {
        log::debug!(
            "web_search skipping DDGS fallback (DDGS disabled), query={}",
            query
        );
        return vec![];
    }
    log::debug!(
        "provider web_search returned empty for {}, falling back to DDGS",
        query
    );
    log::debug!("web_search using DDGS backend, query={}", query);
    web_search(query)
}

/// Fetch a single URL, extracting text content.
/// Matches Python's web_fetch() — uses cached client, GitHub API conversion.
pub fn web_fetch(url: &str) -> String {
    log::debug!("web_fetch url={}", url);

    let client = match get_fetch_client() {
        Some(c) => c,
        None => return "Failed to build fetch HTTP client".to_string(),
    };
    let resolved_url = github_url_to_api(url).unwrap_or_else(|| url.to_string());

    let mut headers: HashMap<&str, &str> = HashMap::new();
    if resolved_url.contains("api.github.com") {
        headers.insert("Accept", "application/vnd.github+json");
    }

    let mut req = client.get(&resolved_url);
    for (k, v) in &headers {
        req = req.header(*k, *v);
    }

    match req.send() {
        Ok(response) => {
            if let Err(e) = response.error_for_status_ref() {
                log::warn!("web_fetch failed for {}: {}", resolved_url, e);
                return format!("Failed to fetch: {e}");
            }

            if resolved_url.contains("api.github.com") {
                match response.json::<serde_json::Value>() {
                    Ok(json) => {
                        let formatted = format_github_api(&json, &resolved_url);
                        log::debug!(
                            "web_fetch got {} chars from {}",
                            formatted.len(),
                            resolved_url
                        );
                        log::debug!(
                            "web_fetch content={}",
                            formatted.chars().take(2000).collect::<String>()
                        );
                        return formatted;
                    }
                    Err(e) => {
                        log::warn!("web_fetch failed for {}: {}", resolved_url, e);
                        return format!("Failed to fetch: {e}");
                    }
                }
            }

            match response.text() {
                Ok(html) => {
                    let mut text = extract_text(&html);
                    if text.len() > FETCH_MAX_CHARS {
                        text = format!(
                            "{}...<truncated>",
                            text.chars().take(FETCH_MAX_CHARS).collect::<String>()
                        );
                    }
                    log::debug!(
                        "web_fetch got {} chars from {}",
                        text.len(),
                        resolved_url
                    );
                    log::debug!(
                        "web_fetch content={}",
                        text.chars().take(2000).collect::<String>()
                    );
                    text
                }
                Err(e) => {
                    log::warn!("web_fetch failed for {}: {}", resolved_url, e);
                    format!("Failed to fetch: {e}")
                }
            }
        }
        Err(e) => {
            log::warn!("web_fetch failed for {}: {}", resolved_url, e);
            format!("Failed to fetch: {e}")
        }
    }
}

/// Fetch multiple URLs in parallel and return a map of URL → content.
/// Matches Python's web_fetch_batch() — ThreadPoolExecutor with max_workers=min(len(urls), 5).
pub fn web_fetch_batch(urls: &[String]) -> HashMap<String, String> {
    use rayon::prelude::*;
    use std::sync::Mutex;

    let results: Mutex<HashMap<String, String>> = Mutex::new(HashMap::new());

    urls.par_iter().for_each(|url| {
        let content = web_fetch(url);
        match results.lock() {
            Ok(mut map) => {
                map.insert(url.clone(), content);
            }
            Err(e) => {
                // Mutex poisoned — recover the data from the poisoned lock.
                log::warn!("web_fetch_batch mutex poisoned, recovering data");
                let mut map = e.into_inner();
                map.insert(url.clone(), content);
            }
        }
    });

    results.into_inner().unwrap_or_else(|e| e.into_inner())
}

/// Convert a GitHub URL to the API equivalent.
/// Matches Python's _github_url_to_api().
fn github_url_to_api(url: &str) -> Option<String> {
    let caps = GITHUB_REPO_RE.captures(url)?;
    let repo = caps.get(1)?.as_str();
    // If the URL ends with /releases or just the repo root, get latest release
    if url.ends_with("/releases") || !url.contains("/releases/") {
        Some(format!(
            "https://api.github.com/repos/{}/releases/latest",
            repo
        ))
    } else {
        None
    }
}

/// Format GitHub API release data.
/// Matches Python's _format_github_api().
fn format_github_api(data: &serde_json::Value, _url: &str) -> String {
    let item = if let Some(arr) = data.as_array() {
        if arr.is_empty() {
            return "No releases found.".to_string();
        }
        &arr[0]
    } else {
        data
    };

    if let Some(obj) = item.as_object() {
        let tag = obj
            .get("tag_name")
            .or_else(|| obj.get("name"))
            .and_then(|v| v.as_str())
            .unwrap_or("");
        let body = obj
            .get("body")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        let body_short: String = body.chars().take(1500).collect();
        let published = obj
            .get("published_at")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        format!("Tag: {}\nPublished: {}\nRelease Notes:\n{}", tag, published, body_short)
    } else {
        serde_json::to_string(item)
            .unwrap_or_default()
            .chars()
            .take(FETCH_MAX_CHARS)
            .collect()
    }
}

/// Extract plain text from HTML.
/// Matches Python's _extract_text().
fn extract_text(html: &str) -> String {
    static RE_SCRIPT: Lazy<Regex> =
        Lazy::new(|| Regex::new(r"(?is)<script[^>]*>.*?</script>").unwrap());
    static RE_STYLE: Lazy<Regex> =
        Lazy::new(|| Regex::new(r"(?is)<style[^>]*>.*?</style>").unwrap());
    static RE_TAGS: Lazy<Regex> = Lazy::new(|| Regex::new(r"<[^>]+>").unwrap());
    static RE_WS: Lazy<Regex> = Lazy::new(|| Regex::new(r"\s+").unwrap());

    let cleaned = RE_SCRIPT.replace_all(html, "");
    let cleaned = RE_STYLE.replace_all(&cleaned, "");
    let text = RE_TAGS.replace_all(&cleaned, " ");
    RE_WS.replace_all(&text, " ").trim().to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_github_url_to_api_root() {
        let api = github_url_to_api("https://github.com/hpy/frais/");
        assert!(api.is_some());
        assert!(api.unwrap().contains("api.github.com"));
    }

    #[test]
    fn test_github_url_to_api_no_trailing_slash() {
        let api = github_url_to_api("https://github.com/hpy/frais");
        assert!(api.is_some());
    }

    #[test]
    fn test_github_url_to_api_releases() {
        let api = github_url_to_api("https://github.com/hpy/frais/releases");
        assert!(api.is_some());
        assert!(api.unwrap().contains("releases/latest"));
    }

    #[test]
    fn test_github_url_to_api_non_github() {
        let api = github_url_to_api("https://example.com/project");
        assert!(api.is_none());
    }

    #[test]
    fn test_extract_text_removes_tags() {
        let html = "<html><body><p>Hello</p> <p>World</p></body></html>";
        let text = extract_text(html);
        assert!(text.contains("Hello"));
        assert!(text.contains("World"));
    }

    #[test]
    fn test_extract_text_removes_scripts() {
        let html = "<html><script>alert('xss')</script><p>Safe</p></html>";
        let text = extract_text(html);
        assert!(!text.contains("alert"));
        assert!(text.contains("Safe"));
    }

    #[test]
    fn test_format_github_api_dict() {
        let data = serde_json::json!({
            "tag_name": "v1.0.0",
            "published_at": "2024-01-01",
            "body": "First release"
        });
        let result = format_github_api(&data, "");
        assert!(result.contains("v1.0.0"));
        assert!(result.contains("First release"));
    }

    #[test]
    fn test_format_github_api_arr() {
        let data = serde_json::json!([]);
        let result = format_github_api(&data, "");
        assert!(result.contains("No releases found"));
    }

    #[test]
    fn test_urlencoding_alphanumeric_preserved() {
        let encoded = urlencoding("hello world");
        assert_eq!(encoded, "hello+world");
    }

    #[test]
    fn test_urlencoding_special_chars_encoded() {
        let encoded = urlencoding("hello@world.com");
        assert!(encoded.contains("%40"));
    }
}
