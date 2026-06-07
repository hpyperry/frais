//! Coordinator — matches Python's frais/coordinator.py.
//! Orchestrates plugin selection, parallel scanning, and summary generation.

use crate::models::{PluginScanResult, ScanResult, SystemProfile, UpdateCandidate};
use crate::plugins::ScannerPlugin;
use crate::store::plugin_store;
use std::collections::BTreeMap;

/// Select plugins to use based on explicit names, persisted state, and defaults.
/// Returns (selected_names, warnings).
/// Matches Python's select_plugins().
pub fn select_plugins(
    explicit: Option<&[String]>,
    all_plugins: &BTreeMap<String, Box<dyn ScannerPlugin>>,
) -> (Vec<String>, Vec<String>) {
    let persisted = plugin_store::load_plugins_config(&crate::paths::plugins_config_path());
    let mut selected = Vec::new();
    let mut warnings = Vec::new();

    if let Some(names) = explicit {
        for name in names {
            let name = name.trim();
            if !all_plugins.contains_key(name) {
                log::warn!("unknown plugin: {}", name);
                warnings.push(format!("Unknown plugin: {name}"));
                continue;
            }
            if let Some(&enabled) = persisted.get(name) {
                if !enabled {
                    log::warn!("plugin is disabled: {}", name);
                    warnings.push(format!("Plugin is disabled: {name}"));
                    continue;
                }
            }
            selected.push(name.to_string());
        }
    } else {
        for (name, plugin) in all_plugins {
            let enabled = persisted
                .get(name)
                .copied()
                .unwrap_or_else(|| plugin.enabled_by_default());
            if enabled {
                selected.push(name.clone());
            }
        }
    }

    (selected, warnings)
}

/// Run all plugin scans concurrently via thread::scope.
/// Each plugin drives its own internal concurrency.
/// Matches Python's run_scan() — ThreadPoolExecutor + try/except per plugin.
#[allow(clippy::type_complexity)]
pub fn run_scan(
    selected: &[String],
    all_plugins: &BTreeMap<String, Box<dyn ScannerPlugin>>,
    system: &SystemProfile,
    show_all: bool,
    jobs: usize,
    on_plugin_progress: Option<&(dyn Fn(&str, usize, usize, usize) + Send + Sync)>,
    on_plugin_done: Option<&(dyn Fn(&str, &PluginScanResult) + Send + Sync)>,
) -> ScanResult {
    let mut plugin_results = BTreeMap::new();

    // channel for as_completed() semantics — matches Python's as_completed()
    let (tx, rx) = std::sync::mpsc::channel::<(String, PluginScanResult)>();

    std::thread::scope(|s| {
        for name in selected {
            let plugin = match all_plugins.get(name) {
                Some(p) => p,
                None => {
                    log::warn!("plugin disappeared during scan: {name}");
                    continue;
                }
            };

            let name_clone = name.clone();
            let tx = tx.clone();

            // Build progress wrapper — Send+Sync closure that embeds plugin name.
            // The plugin calls this from its worker threads, so it must be Sync.
            let progress_wrapper: Option<Box<dyn Fn(usize, usize, usize) + Send + Sync>> =
                on_plugin_progress.map(|cb| {
                    let pname = name_clone.clone();
                    Box::new(move |step, done, total| cb(&pname, step, done, total))
                        as Box<dyn Fn(usize, usize, usize) + Send + Sync>
                });

            // thread::scope allows borrowing `system` directly (it outlives all spawned threads)
            s.spawn(move || {
                // Coerce &dyn Fn + Send + Sync → &dyn Fn + Sync
                let progress_ref: Option<&(dyn Fn(usize, usize, usize) + Sync)> =
                    match &progress_wrapper {
                        Some(w) => Some(w.as_ref()),
                        None => None,
                    };

                // catch_unwind so a plugin panic is captured as a skipped result
                // instead of killing the entire scan — matches Python's try/except
                let pr = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                    if show_all {
                        plugin.scan_all(system, progress_ref, jobs)
                    } else {
                        plugin.scan(system, progress_ref, jobs)
                    }
                }))
                .unwrap_or_else(|panic| {
                    let msg = panic
                        .downcast_ref::<&str>()
                        .map(|s| s.to_string())
                        .or_else(|| panic.downcast_ref::<String>().cloned())
                        .unwrap_or_else(|| "unknown panic".to_string());
                    log::warn!("scan failed: plugin panicked: {}", msg);
                    PluginScanResult {
                        skipped: vec![format!("plugin panicked: {msg}")],
                        ..PluginScanResult::default()
                    }
                });
                let _ = tx.send((name_clone, pr));
            });
        }
        // Drop the original tx so rx will close after all spawned senders finish.
        drop(tx);

        // Receive results in completion order — matches Python's as_completed()
        for (name, pr) in rx {
            if let Some(ref cb) = on_plugin_done {
                cb(&name, &pr);
            }
            plugin_results.insert(name, pr);
        }
    });

    ScanResult {
        system: system.clone(),
        plugin_results,
    }
}

/// Generate summaries for all candidates via their owning plugins.
/// Uses rayon for parallel execution via par_iter_mut().
/// Matches Python's run_summaries() — ThreadPoolExecutor + plugin.summarize().
pub fn run_summaries(
    llm: &dyn crate::llm::base::LLMClient,
    candidates: &mut [UpdateCandidate],
    candidate_plugins: &BTreeMap<usize, String>,
    plugins: &BTreeMap<String, Box<dyn ScannerPlugin>>,
    _max_workers: usize,
    on_progress: Option<&(dyn Fn() + Sync)>,
    language: &str,
) {
    use rayon::prelude::*;

    if candidates.is_empty() {
        return;
    }

    // Parallel iteration over candidates — par_iter_mut() gives non-overlapping
    // &mut references, matching Python's ThreadPoolExecutor.submit() pattern
    // where each candidate is handed to its own plugin.summarize() call.
    candidates
        .par_iter_mut()
        .enumerate()
        .filter(|(_i, c)| c.ai_summary.is_none())
        .for_each(|(i, c)| {
            let pname = match candidate_plugins.get(&i) {
                Some(pn) => pn,
                None => return,
            };
            let plugin = match plugins.get(pname) {
                Some(p) => p,
                None => return,
            };
            if let Err(e) = plugin.summarize(llm, c, language) {
                log::warn!("summary failed: {}", e);
            }
            if let Some(ref cb) = on_progress {
                cb();
            }
        });
}

#[cfg(test)]
mod tests {
    use super::*;
    

    struct TestPlugin {
        name: &'static str,
        available: bool,
        enabled_default: bool,
        scan_result: PluginScanResult,
    }

    impl ScannerPlugin for TestPlugin {
        fn name(&self) -> &'static str {
            self.name
        }
        fn enabled_by_default(&self) -> bool {
            self.enabled_default
        }
        fn is_available(&self) -> bool {
            self.available
        }
        fn scan(
            &self,
            _system: &SystemProfile,
            _on_progress: Option<&(dyn Fn(usize, usize, usize) + Sync)>,
            _max_workers: usize,
        ) -> PluginScanResult {
            self.scan_result.clone()
        }
    }

    fn make_plugins() -> BTreeMap<String, Box<dyn ScannerPlugin>> {
        let mut m: BTreeMap<String, Box<dyn ScannerPlugin>> = BTreeMap::new();
        m.insert(
            "test1".into(),
            Box::new(TestPlugin {
                name: "test1",
                available: true,
                enabled_default: true,
                scan_result: PluginScanResult::default(),
            }),
        );
        m.insert(
            "test2".into(),
            Box::new(TestPlugin {
                name: "test2",
                available: true,
                enabled_default: false,
                scan_result: PluginScanResult::default(),
            }),
        );
        m
    }

    #[test]
    fn test_select_plugins_returns_enabled_only() {
        let plugins = make_plugins();
        let (selected, warnings) = select_plugins(None, &plugins);
        assert!(warnings.is_empty());
        assert!(selected.contains(&"test1".to_string()));
        assert!(!selected.contains(&"test2".to_string()));
    }

    #[test]
    fn test_select_plugins_with_explicit_names() {
        let plugins = make_plugins();
        let explicit = vec!["test2".to_string()];
        let (selected, warnings) = select_plugins(Some(&explicit), &plugins);
        assert!(selected.contains(&"test2".to_string()));
        assert!(warnings.is_empty());
    }

    #[test]
    fn test_select_plugins_warns_unknown() {
        let plugins = make_plugins();
        let explicit = vec!["nonexistent".to_string()];
        let (_selected, warnings) = select_plugins(Some(&explicit), &plugins);
        assert!(!warnings.is_empty());
        assert!(warnings[0].contains("Unknown"));
    }

    #[test]
    fn test_run_scan_parallel() {
        let plugins = make_plugins();
        let system = SystemProfile {
            os_name: "macOS".into(),
            os_version: "15.0".into(),
            arch: "arm64".into(),
            applications_paths: vec![],
        };
        let selected = vec!["test1".to_string(), "test2".to_string()];
        let result = run_scan(&selected, &plugins, &system, false, 10, None, None);
        assert_eq!(result.plugin_results.len(), 2);
    }
}
