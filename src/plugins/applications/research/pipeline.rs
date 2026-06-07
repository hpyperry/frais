// 3-step structured LLM research pipeline — matches Python's research/pipeline.py.
use std::collections::{HashMap, HashSet};
use std::time::Instant;

use crate::llm::base::{LLMClient, SearchResult};
use crate::models::{ResearchResult, SoftwareItem, UpdateCandidate};
use crate::web_tools;

use super::super::app_store::check_app_store_version;
use super::candidate_factory::make_candidate;
use super::json_parser::{ensure_list, parse_json_list, parse_json_object};
use super::prompts;
use super::version_compare::is_newer;

/// Research latest version for an application using two-tier strategy.
/// Tier 1: App Store apps via iTunes API (~1s fast path).
/// Tier 2: LLM-driven 3-step structured research.
/// Matches Python's research_application_update exactly.
pub fn research_application_update(
    llm: &dyn LLMClient,
    item: &SoftwareItem,
) -> Option<UpdateCandidate> {
    // Tier 1: App Store apps via iTunes API (~1s)
    let (latest, track_id) = check_app_store_version(item);
    if let Some(ref version) = latest {
        if is_newer(item.current_version.as_deref(), Some(version)) {
            log::info!(
                "research result name={} source=itunes version={} (current={})",
                item.name,
                version,
                item.current_version.as_deref().unwrap_or("unknown")
            );
            return Some(make_candidate(
                item.clone(),
                version.clone(),
                None,
                "itunes",
                track_id,
            ));
        }
        log::info!(
            "research result name={} source=itunes up-to-date (version={})",
            item.name,
            version
        );
        return None;
    }

    // Tier 2: LLM-driven structured research
    let t0 = Instant::now();
    let result = llm_structured_research(llm, item);
    let elapsed = t0.elapsed().as_secs_f64();

    if let Some(ref result) = result {
        if let Some(ref version) = result.latest_version {
            if is_newer(item.current_version.as_deref(), Some(version)) {
                log::info!(
                    "research result name={} source=llm version={} (current={}) elapsed={:.1}s",
                    item.name,
                    version,
                    item.current_version.as_deref().unwrap_or("unknown"),
                    elapsed
                );
                return Some(make_candidate(
                    item.clone(),
                    version.clone(),
                    Some(result),
                    "llm",
                    None,
                ));
            }
        }
    }

    log::info!(
        "research result name={} source=llm up-to-date elapsed={:.1}s",
        item.name,
        elapsed
    );
    None
}

/// 3-step structured research: LLM generates queries, we search & fetch, LLM extracts version.
/// Matches Python's _llm_structured_research exactly.
fn llm_structured_research(llm: &dyn LLMClient, item: &SoftwareItem) -> Option<ResearchResult> {
    // Step 1: LLM generates search queries
    let queries = match generate_search_queries(llm, item) {
        Ok(q) => q,
        Err(e) => {
            log::warn!("generate_search_queries failed for {}: {}", item.name, e);
            return None;
        }
    };

    if queries.is_empty() {
        log::info!("no search queries generated for {}", item.name);
        return None;
    }

    log::info!("generated {} queries for {}", queries.len(), item.name);
    log::debug!("queries for {}: {:?}", item.name, queries);

    // Execute all searches in parallel
    let unique_results = execute_searches(llm, &queries);

    if unique_results.is_empty() {
        log::info!("no search results for {}", item.name);
        return None;
    }

    log::info!(
        "found {} unique search results for {}",
        unique_results.len(),
        item.name
    );

    // Step 2: LLM picks best URLs
    let urls = match pick_urls(llm, item, &unique_results) {
        Ok(u) => u,
        Err(e) => {
            log::warn!("pick_urls failed for {}: {}", item.name, e);
            return None;
        }
    };

    if urls.is_empty() {
        log::info!("no URLs picked for {}", item.name);
        return None;
    }

    log::info!("picked {} URLs for {}", urls.len(), item.name);
    log::debug!("urls for {}: {:?}", item.name, urls);

    // Fetch all picked URLs
    let fetched = web_tools::web_fetch_batch(&urls);

    // Step 3: LLM extracts version from fetched content
    match extract_version(llm, item, &fetched) {
        Ok(result) => result,
        Err(e) => {
            log::warn!("extract_version failed for {}: {}", item.name, e);
            None
        }
    }
}

/// Step 1: Generate 2-3 search queries via LLM.
/// System: SEARCH_QUERIES_PROMPT, User: concise app info.
/// Matches Python's generate_search_queries exactly.
fn generate_search_queries(
    llm: &dyn LLMClient,
    item: &SoftwareItem,
) -> Result<Vec<String>, String> {
    let user_msg = format!(
        "App: {}, bundle: {}, current: {}, source: {}.",
        item.name,
        item.id,
        item.current_version.as_deref().unwrap_or("unknown"),
        item.source.as_str()
    );

    log::debug!("step1 prompt for {}: {}", item.name, user_msg);

    let text = llm
        .chat(prompts::SEARCH_QUERIES_PROMPT, &user_msg, None, true)
        .map_err(|e| format!("LLM error: {}", e))?;

    log::debug!("step1 response for {}: {}", item.name, text);

    // parse_json_list returns empty vec on failure — matches Python's _parse_json_list
    Ok(parse_json_list(&text))
}

/// Execute all searches, deduplicate by URL.
/// Each query is searched independently with error handling.
/// Matches Python's parallel search execution with dedup and per-query try/except.
fn execute_searches(llm: &dyn LLMClient, queries: &[String]) -> Vec<SearchResult> {
    use rayon::prelude::*;

    // Execute all searches in parallel with per-query panic recovery.
    // web_search_strategy handles its own internal errors — this catch_unwind is
    // a safety net for unexpected panics, matching Python's try/except per future.
    let all_results: Vec<Vec<SearchResult>> = queries
        .par_iter()
        .map(|query| {
            match std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                web_tools::web_search_strategy(llm, query)
            })) {
                Ok(results) => results,
                Err(panic_err) => {
                    let msg = panic_err
                        .downcast_ref::<&str>()
                        .map(|s| s.to_string())
                        .or_else(|| panic_err.downcast_ref::<String>().cloned())
                        .unwrap_or_else(|| "unknown panic".to_string());
                    log::warn!("web_search failed for query={}: {}", query, msg);
                    vec![]
                }
            }
        })
        .collect();

    // Deduplicate by URL — matches Python's seen_urls dedup logic
    let mut seen_urls: HashSet<String> = HashSet::new();
    let mut unique_results: Vec<SearchResult> = Vec::new();

    for results in all_results {
        for r in results {
            if !r.url.is_empty() && !seen_urls.contains(&r.url) {
                seen_urls.insert(r.url.clone());
                unique_results.push(r);
            }
        }
    }

    unique_results
}

/// Step 2: Pick best URLs from search results.
/// System: PICK_URLS_PROMPT, User: app name + JSON search results.
/// Matches Python's pick_urls exactly.
fn pick_urls(
    llm: &dyn LLMClient,
    item: &SoftwareItem,
    search_results: &[SearchResult],
) -> Result<Vec<String>, String> {
    let results_json: Vec<serde_json::Value> = search_results
        .iter()
        .map(|r| {
            serde_json::json!({
                "title": r.title,
                "url": r.url,
                "snippet": r.snippet,
            })
        })
        .collect();

    let results_text = serde_json::to_string(&results_json).unwrap_or_default();
    let user_msg = format!("App: {}\n\nSearch results:\n{}", item.name, results_text);

    log::debug!(
        "step2 input for {}: {}",
        item.name,
        &results_text.chars().take(2000).collect::<String>()
    );

    let text = llm
        .chat(prompts::PICK_URLS_PROMPT, &user_msg, None, true)
        .map_err(|e| format!("LLM error: {}", e))?;

    log::debug!("step2 response for {}: {}", item.name, text);

    // parse_json_list returns empty vec on failure — matches Python's _parse_json_list
    let urls = parse_json_list(&text);
    Ok(urls.into_iter().take(5).collect())
}

/// Step 3: Extract version info from fetched content.
/// System: EXTRACT_VERSION_PROMPT, User: app info + JSON content (truncated to 3000 chars/URL).
/// Matches Python's extract_version exactly.
fn extract_version(
    llm: &dyn LLMClient,
    item: &SoftwareItem,
    fetched_content: &HashMap<String, String>,
) -> Result<Option<ResearchResult>, String> {
    let content_json: Vec<serde_json::Value> = fetched_content
        .iter()
        .map(|(url, content)| {
            let truncated: String = if content.chars().count() > 3000 {
                content.chars().take(3000).collect()
            } else {
                content.clone()
            };
            serde_json::json!({
                "url": url,
                "content": truncated,
            })
        })
        .collect();

    let content_text = serde_json::to_string(&content_json).unwrap_or_default();
    let user_msg = format!(
        "App: {}, current version: {}\n\nPage contents:\n{}",
        item.name,
        item.current_version.as_deref().unwrap_or("unknown"),
        content_text
    );

    log::debug!(
        "step3 input for {}: {}",
        item.name,
        &content_text.chars().take(2000).collect::<String>()
    );

    let text = llm
        .chat(prompts::EXTRACT_VERSION_PROMPT, &user_msg, None, true)
        .map_err(|e| format!("LLM error: {}", e))?;

    log::debug!("step3 response for {}: {}", item.name, text);

    // parse_json_object returns empty object on failure — matches Python's _parse_json_object
    let data = parse_json_object(&text);

    log::debug!("step3 result for {}: {:?}", item.name, data);

    let confidence = data
        .get("confidence")
        .and_then(|v| v.as_str())
        .unwrap_or("unknown")
        .to_string();

    if confidence == "none" {
        log::info!(
            "research step3 name={} skipped (page content mismatch)",
            item.name
        );
        return Ok(None);
    }

    let result = ResearchResult {
        latest_version: data
            .get("latest_version")
            .and_then(|v| v.as_str())
            .filter(|s| *s != "null" && !s.is_empty())
            .map(|s| s.to_string()),
        release_notes_url: data
            .get("release_notes_url")
            .and_then(|v| v.as_str())
            .filter(|s| *s != "null")
            .map(|s| s.to_string()),
        download_url: data
            .get("download_url")
            .and_then(|v| v.as_str())
            .filter(|s| *s != "null")
            .map(|s| s.to_string()),
        source_repo_url: data
            .get("source_repo_url")
            .and_then(|v| v.as_str())
            .filter(|s| *s != "null")
            .map(|s| s.to_string()),
        confidence: confidence.clone(),
        evidence: data
            .get("evidence")
            .map(|v| ensure_list(v).unwrap_or_default())
            .unwrap_or_default(),
        release_notes: data
            .get("release_notes")
            .and_then(|v| v.as_str())
            .filter(|s| *s != "null")
            .map(|s| s.to_string()),
    };

    Ok(Some(result))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::llm::base::LLMRequestError;
    use std::collections::BTreeMap;

    /// Fake LLM for testing pipeline functions (thread-safe).
    struct FakeLLM {
        responses: Vec<String>,
        call_count: std::sync::atomic::AtomicUsize,
    }

    impl FakeLLM {
        fn new(responses: Vec<String>) -> Self {
            FakeLLM {
                responses,
                call_count: std::sync::atomic::AtomicUsize::new(0),
            }
        }
    }

    impl LLMClient for FakeLLM {
        fn chat(
            &self,
            _system: &str,
            _user: &str,
            _max_tokens: Option<u32>,
            _disable_thinking: bool,
        ) -> Result<String, LLMRequestError> {
            let idx = self
                .call_count
                .fetch_add(1, std::sync::atomic::Ordering::SeqCst);
            if idx < self.responses.len() {
                Ok(self.responses[idx].clone())
            } else {
                Ok("[]".into())
            }
        }

        fn close(&self) {}

        fn web_search(&self, _query: &str) -> Vec<SearchResult> {
            vec![SearchResult {
                title: "Test Result".into(),
                url: "https://example.com/releases".into(),
                snippet: "Latest version info".into(),
            }]
        }
    }

    fn make_test_item() -> SoftwareItem {
        SoftwareItem {
            id: "com.test.app".into(),
            name: "TestApp".into(),
            kind: "application".into(),
            source: crate::models::SourceKind::NetworkDownload,
            current_version: Some("1.0.0".into()),
            path: None,
            metadata: BTreeMap::new(),
        }
    }

    #[test]
    fn test_generate_search_queries_parses_json_array() {
        let llm = FakeLLM::new(vec!["[\"query1\", \"query2\"]".into()]);
        let item = make_test_item();
        let queries = generate_search_queries(&llm, &item);
        assert!(queries.is_ok());
        let q = queries.unwrap();
        assert_eq!(q.len(), 2);
        assert_eq!(q[0], "query1");
    }

    #[test]
    fn test_generate_search_queries_empty_on_parse_failure() {
        // Matches Python: _parse_json_list returns [] on parse failure, no error raised
        let llm = FakeLLM::new(vec!["not valid json".into()]);
        let item = make_test_item();
        let result = generate_search_queries(&llm, &item);
        assert!(result.is_ok());
        assert!(result.unwrap().is_empty());
    }

    #[test]
    fn test_pick_urls_limits_to_5() {
        let llm = FakeLLM::new(vec![
            "[\"https://a.com\", \"https://b.com\", \"https://c.com\", \
              \"https://d.com\", \"https://e.com\", \"https://f.com\"]"
                .into(),
        ]);
        let item = make_test_item();
        let results = vec![SearchResult {
            title: "Test".into(),
            url: "https://example.com".into(),
            snippet: "Info".into(),
        }];
        let urls = pick_urls(&llm, &item, &results);
        assert!(urls.is_ok());
        assert_eq!(urls.unwrap().len(), 5);
    }

    #[test]
    fn test_extract_version_returns_none_when_confidence_none() {
        let llm = FakeLLM::new(vec![
            "{\"latest_version\":null,\"confidence\":\"none\",\"evidence\":[]}".into(),
        ]);
        let item = make_test_item();
        let mut content = HashMap::new();
        content.insert("https://example.com".into(), "Some content".into());
        let result = extract_version(&llm, &item, &content);
        assert!(result.is_ok());
        assert!(result.unwrap().is_none());
    }

    #[test]
    fn test_extract_version_parses_full_result() {
        let llm = FakeLLM::new(vec![
            r#"{"latest_version":"2.0.0","confidence":"high","release_notes_url":"https://example.com/notes","download_url":"https://example.com/dl","source_repo_url":"https://github.com/test/app","evidence":["https://example.com"],"release_notes":"Bug fixes"}"#.into(),
        ]);
        let item = make_test_item();
        let mut content = HashMap::new();
        content.insert("https://example.com".into(), "Content".into());
        let result = extract_version(&llm, &item, &content);
        assert!(result.is_ok());
        let r = result.unwrap().unwrap();
        assert_eq!(r.latest_version, Some("2.0.0".into()));
        assert_eq!(r.confidence, "high");
        assert_eq!(r.evidence.len(), 1);
    }

    #[test]
    fn test_execute_searches_deduplicates_by_url() {
        struct DedupLLM;
        impl LLMClient for DedupLLM {
            fn chat(
                &self,
                _system: &str,
                _user: &str,
                _max_tokens: Option<u32>,
                _disable_thinking: bool,
            ) -> Result<String, LLMRequestError> {
                Ok("[]".into())
            }
            fn close(&self) {}
            fn web_search(&self, _query: &str) -> Vec<SearchResult> {
                vec![
                    SearchResult {
                        title: "A".into(),
                        url: "https://same.com".into(),
                        snippet: "Same URL".into(),
                    },
                    SearchResult {
                        title: "B".into(),
                        url: "https://same.com".into(),
                        snippet: "Duplicate".into(),
                    },
                ]
            }
        }
        let llm = DedupLLM;
        let queries = vec!["q1".into(), "q2".into()];
        let results = execute_searches(&llm, &queries);
        // Same URL should be deduplicated
        assert_eq!(results.len(), 1);
    }

    #[test]
    fn test_llm_structured_research_full_pipeline() {
        let responses = vec![
            // Step 1: search queries
            "[\"test app latest version\", \"test app github releases\"]".into(),
            // Step 2: pick URLs
            "[\"https://example.com/releases\"]".into(),
            // Step 3: extract version
            r#"{"latest_version":"2.0.0","confidence":"high","release_notes_url":null,"download_url":null,"source_repo_url":null,"evidence":["https://example.com/releases"],"release_notes":null}"#.into(),
        ];
        struct PipelineLLM {
            responses: Vec<String>,
            call_count: std::sync::atomic::AtomicUsize,
        }
        impl LLMClient for PipelineLLM {
            fn chat(
                &self,
                _system: &str,
                _user: &str,
                _max_tokens: Option<u32>,
                _disable_thinking: bool,
            ) -> Result<String, LLMRequestError> {
                let idx = self
                    .call_count
                    .fetch_add(1, std::sync::atomic::Ordering::SeqCst);
                if idx < self.responses.len() {
                    Ok(self.responses[idx].clone())
                } else {
                    Ok("[]".into())
                }
            }
            fn close(&self) {}
            fn web_search(&self, _query: &str) -> Vec<SearchResult> {
                vec![SearchResult {
                    title: "Test".into(),
                    url: "https://example.com/releases".into(),
                    snippet: "Version 2.0.0".into(),
                }]
            }
        }

        let llm = PipelineLLM {
            responses,
            call_count: std::sync::atomic::AtomicUsize::new(0),
        };
        let item = make_test_item();
        let candidate = research_application_update(&llm, &item);
        assert!(candidate.is_some());
        let c = candidate.unwrap();
        assert_eq!(c.latest_version, Some("2.0.0".into()));
        assert_eq!(c.evidence, vec!["https://example.com/releases"]);
    }

    #[test]
    fn test_llm_structured_research_no_update_needed() {
        // Version same as current
        let responses = vec![
            "[\"test app latest version\"]".into(),
            "[\"https://example.com/releases\"]".into(),
            r#"{"latest_version":"1.0.0","confidence":"high","evidence":[]}"#.into(),
        ];
        struct NoUpdateLLM {
            responses: Vec<String>,
            call_count: std::sync::atomic::AtomicUsize,
        }
        impl LLMClient for NoUpdateLLM {
            fn chat(
                &self,
                _system: &str,
                _user: &str,
                _max_tokens: Option<u32>,
                _disable_thinking: bool,
            ) -> Result<String, LLMRequestError> {
                let idx = self
                    .call_count
                    .fetch_add(1, std::sync::atomic::Ordering::SeqCst);
                Ok(self.responses.get(idx).cloned().unwrap_or_default())
            }
            fn close(&self) {}
            fn web_search(&self, _query: &str) -> Vec<SearchResult> {
                vec![SearchResult {
                    title: "Test".into(),
                    url: "https://example.com".into(),
                    snippet: "Info".into(),
                }]
            }
        }

        let llm = NoUpdateLLM {
            responses,
            call_count: std::sync::atomic::AtomicUsize::new(0),
        };
        let item = make_test_item();
        let candidate = research_application_update(&llm, &item);
        assert!(candidate.is_none());
    }

    // --- Error resilience tests ---

    #[test]
    fn test_pipeline_handles_step1_llm_error() {
        // Step 1 returns an error — pipeline should return None gracefully
        struct ErrorLLM;
        impl LLMClient for ErrorLLM {
            fn chat(
                &self,
                _system: &str,
                _user: &str,
                _max_tokens: Option<u32>,
                _disable_thinking: bool,
            ) -> Result<String, LLMRequestError> {
                Err(LLMRequestError::new("simulated LLM failure"))
            }
            fn close(&self) {}
            fn web_search(&self, _query: &str) -> Vec<SearchResult> {
                vec![]
            }
        }

        let llm = ErrorLLM;
        let item = make_test_item();
        let result = research_application_update(&llm, &item);
        assert!(result.is_none());
    }

    #[test]
    fn test_pipeline_handles_step1_empty_queries() {
        // Step 1 returns empty array — pipeline should return None
        struct EmptyQueriesLLM;
        impl LLMClient for EmptyQueriesLLM {
            fn chat(
                &self,
                _system: &str,
                _user: &str,
                _max_tokens: Option<u32>,
                _disable_thinking: bool,
            ) -> Result<String, LLMRequestError> {
                Ok("[]".into())
            }
            fn close(&self) {}
        }

        let llm = EmptyQueriesLLM;
        let item = make_test_item();
        let result = research_application_update(&llm, &item);
        assert!(result.is_none());
    }

    #[test]
    fn test_pipeline_handles_step2_no_urls_picked() {
        // Step 2 returns empty array — pipeline should return None
        struct NoUrlsLLM {
            call_count: std::sync::atomic::AtomicUsize,
        }
        impl LLMClient for NoUrlsLLM {
            fn chat(
                &self,
                _system: &str,
                _user: &str,
                _max_tokens: Option<u32>,
                _disable_thinking: bool,
            ) -> Result<String, LLMRequestError> {
                let idx = self
                    .call_count
                    .fetch_add(1, std::sync::atomic::Ordering::SeqCst);
                match idx {
                    0 => Ok("[\"test query\"]".into()), // Step 1: queries
                    _ => Ok("[]".into()),               // Step 2: empty URLs
                }
            }
            fn close(&self) {}
            fn web_search(&self, _query: &str) -> Vec<SearchResult> {
                vec![SearchResult {
                    title: "Result".into(),
                    url: "https://example.com".into(),
                    snippet: "Info".into(),
                }]
            }
        }

        let llm = NoUrlsLLM {
            call_count: std::sync::atomic::AtomicUsize::new(0),
        };
        let item = make_test_item();
        let result = research_application_update(&llm, &item);
        assert!(result.is_none());
    }

    #[test]
    fn test_pipeline_handles_step3_parse_failure() {
        // Step 3 returns invalid JSON — pipeline should return None
        struct BadJsonLLM {
            call_count: std::sync::atomic::AtomicUsize,
        }
        impl LLMClient for BadJsonLLM {
            fn chat(
                &self,
                _system: &str,
                _user: &str,
                _max_tokens: Option<u32>,
                _disable_thinking: bool,
            ) -> Result<String, LLMRequestError> {
                let idx = self
                    .call_count
                    .fetch_add(1, std::sync::atomic::Ordering::SeqCst);
                match idx {
                    0 => Ok("[\"test query\"]".into()),          // Step 1: queries
                    1 => Ok("[\"https://example.com\"]".into()), // Step 2: URLs
                    _ => Ok("not valid json at all".into()),     // Step 3: bad output
                }
            }
            fn close(&self) {}
            fn web_search(&self, _query: &str) -> Vec<SearchResult> {
                vec![SearchResult {
                    title: "Result".into(),
                    url: "https://example.com".into(),
                    snippet: "Info".into(),
                }]
            }
        }

        let llm = BadJsonLLM {
            call_count: std::sync::atomic::AtomicUsize::new(0),
        };
        let item = make_test_item();
        let result = research_application_update(&llm, &item);
        assert!(result.is_none());
    }

    #[test]
    fn test_pipeline_no_search_results() {
        // web_search returns empty — pipeline should return None
        struct NoSearchLLM;
        impl LLMClient for NoSearchLLM {
            fn chat(
                &self,
                _system: &str,
                _user: &str,
                _max_tokens: Option<u32>,
                _disable_thinking: bool,
            ) -> Result<String, LLMRequestError> {
                Ok("[\"test query\"]".into())
            }
            fn close(&self) {}
            fn web_search(&self, _query: &str) -> Vec<SearchResult> {
                vec![] // Empty results — falls through to DDGS which also returns empty
            }
        }

        let llm = NoSearchLLM;
        let item = make_test_item();
        let result = research_application_update(&llm, &item);
        assert!(result.is_none());
    }

    #[test]
    fn test_extract_version_handles_parse_error_gracefully() {
        // Matches Python: _parse_json_object returns {} on parse failure,
        // extract_version returns ResearchResult with None latest_version
        let llm = FakeLLM::new(vec!["{invalid json".into()]);
        let item = make_test_item();
        let mut content = HashMap::new();
        content.insert("https://example.com".into(), "Content".into());
        let result = extract_version(&llm, &item, &content);
        // With new behavior, parse failure returns empty object → confidence="unknown"
        // → ResearchResult with None latest_version → Ok(Some(result))
        assert!(result.is_ok());
        let research = result.unwrap();
        assert!(research.is_some());
        assert_eq!(research.unwrap().latest_version, None);
    }
}
