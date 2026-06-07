// ApplicationsPlugin — matches Python's frais/plugins/applications/plugin.py.

use crate::models::{PluginScanResult, SourceKind, SystemProfile, UpdateCandidate};
use crate::plugins::ScannerPlugin;

pub struct ApplicationsPlugin;

impl ScannerPlugin for ApplicationsPlugin {
    fn name(&self) -> &'static str { "applications" }
    fn enabled_by_default(&self) -> bool { true }
    fn display_color(&self) -> &'static str { "cyan" }
    fn scan_steps(&self) -> &'static [&'static str] {
        &["discovering apps", "researching latest versions"]
    }
    fn is_available(&self) -> bool { true }

    fn scan(
        &self,
        system: &SystemProfile,
        on_progress: Option<&(dyn Fn(usize, usize, usize) + Sync)>,
        max_workers: usize,
    ) -> PluginScanResult {
        // Step 0: discover all installed applications
        let items = super::discovery::scan_applications(&system.applications_paths);

        log::info!("applications scan found={}", items.len());
        if let Some(cb) = on_progress {
            cb(0, items.len(), items.len());
        }

        // Try to initialize LLM client for research
        let config_path = crate::paths::config_path();
        let config = match crate::store::config_store::load_config(&config_path) {
            Some(c) => c,
            None => {
                log::warn!(
                    "LLM not available for applications research: config not found"
                );
                return PluginScanResult {
                    items,
                    candidates: vec![],
                    skipped: vec!["LLM provider not configured".into()],
                };
            }
        };

        let llm = match crate::llm::get_client(&config, None) {
            Ok(c) => c,
            Err(e) => {
                log::warn!("LLM not available for applications research: {}", e);
                return PluginScanResult {
                    items,
                    candidates: vec![],
                    skipped: vec![e],
                };
            }
        };

        // All items go through research_application_update:
        // - App Store items → iTunes API fast path (~1s)
        // - Non-App Store items → LLM 3-step research pipeline
        // This is an improvement over Python which excluded App Store items from research entirely.
        let to_research: Vec<&crate::models::SoftwareItem> = items.iter().collect();
        let total = to_research.len();

        if let Some(cb) = on_progress {
            cb(1, 0, total);
        }

        if total == 0 {
            llm.close();
            return PluginScanResult {
                items,
                candidates: vec![],
                skipped: vec![],
            };
        }

        // Parallel research with real-time progress via atomic counter.
        // Use rayon ThreadPoolBuilder to respect max_workers — matches Python's ThreadPoolExecutor(max_workers=max_workers).
        let researched = std::sync::atomic::AtomicUsize::new(0);
        let skipped_count = std::sync::atomic::AtomicUsize::new(0);
        let candidates: std::sync::Mutex<Vec<UpdateCandidate>> =
            std::sync::Mutex::new(Vec::new());
        let skipped_items: std::sync::Mutex<Vec<String>> =
            std::sync::Mutex::new(Vec::new());

        let pool_result = rayon::ThreadPoolBuilder::new()
            .num_threads(max_workers.min(total).max(1))
            .build();

        match pool_result {
            Ok(pool) => {
                pool.install(|| {
                    use rayon::prelude::*;
                    to_research.par_iter().for_each(|item| {
                        // Per-item try/except recovery — matches Python's
                        // try: candidate = future.result() except Exception as exc: ...
                        let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                            super::research::pipeline::research_application_update(
                                llm.as_ref(), item,
                            )
                        }));
                        match result {
                            Ok(Some(candidate)) => {
                                if let Ok(mut guard) = candidates.lock() {
                                    guard.push(candidate);
                                }
                            }
                            Ok(None) => {
                                // No update found — normal, not an error
                            }
                            Err(panic_err) => {
                                // Panic in research pipeline — matches Python's except Exception
                                let msg = panic_err
                                    .downcast_ref::<&str>()
                                    .map(|s| s.to_string())
                                    .or_else(|| panic_err.downcast_ref::<String>().cloned())
                                    .unwrap_or_else(|| "unknown panic".to_string());
                                log::warn!(
                                    "research failed for {}: {}",
                                    item.name,
                                    msg
                                );
                                if let Ok(mut guard) = skipped_items.lock() {
                                    guard.push(format!("research failed for {}: {}", item.name, msg));
                                }
                                skipped_count.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
                            }
                        }
                        let count = researched.fetch_add(1, std::sync::atomic::Ordering::SeqCst) + 1;
                        // Real-time progress: called from worker thread — on_progress is Sync.
                        if let Some(cb) = on_progress {
                            cb(1, count, total);
                        }
                    });
                });
            }
            Err(e) => {
                log::warn!("failed to create rayon thread pool: {}", e);
                // Fallback: sequential research with catch_unwind protection
                for item in &to_research {
                    let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                        super::research::pipeline::research_application_update(
                            llm.as_ref(), item,
                        )
                    }));
                    match result {
                        Ok(Some(candidate)) => {
                            candidates.lock().unwrap().push(candidate);
                        }
                        Ok(None) => {}
                        Err(panic_err) => {
                            let msg = panic_err
                                .downcast_ref::<&str>()
                                .map(|s| s.to_string())
                                .or_else(|| panic_err.downcast_ref::<String>().cloned())
                                .unwrap_or_else(|| "unknown panic".to_string());
                            log::warn!("research failed for {}: {}", item.name, msg);
                        }
                    }
                    let count = researched.fetch_add(1, std::sync::atomic::Ordering::SeqCst) + 1;
                    if let Some(cb) = on_progress {
                        cb(1, count, total);
                    }
                }
            }
        }

        let candidates = candidates.into_inner().unwrap_or_else(|e| e.into_inner());
        let mut skipped = skipped_items.into_inner().unwrap_or_else(|e| e.into_inner());
        if skipped_count.load(std::sync::atomic::Ordering::SeqCst) > 0 {
            skipped.push(format!(
                "{} research item(s) failed (see warnings above)",
                skipped_count.load(std::sync::atomic::Ordering::SeqCst)
            ));
        }
        log::info!("applications research done candidates={}", candidates.len());
        llm.close();

        PluginScanResult {
            items,
            candidates,
            skipped,
        }
    }

    fn update(&self, candidate: &UpdateCandidate) -> bool {
        // App Store apps: open macappstore:// URL
        if candidate.item.source == SourceKind::AppStore {
            let (cmd, can_auto) =
                super::app_store::resolve_app_store_command(&candidate.item);
            if can_auto && !cmd.is_empty() {
                let _ = std::process::Command::new(&cmd[0])
                    .args(&cmd[1..])
                    .status();
                return true;
            }
        }
        // Other apps: try subprocess update
        if candidate.can_auto_update && !candidate.command.is_empty() {
            return super::super::ScannerPlugin::update(self, candidate);
        }
        // Manual: confirm before opening the app path — matches Python's typer.confirm()
        if let Some(ref path) = candidate.item.path {
            let confirm = dialoguer::Confirm::new()
                .with_prompt("    Open app for manual update?".to_string())
                .default(false)
                .interact()
                .unwrap_or(false);
            if confirm {
                let _ = std::process::Command::new("open").arg(path).status();
                return true;
            }
            return false;
        }
        false
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_applications_plugin_always_available() {
        let plugin = ApplicationsPlugin;
        assert!(plugin.is_available());
    }

    #[test]
    fn test_applications_plugin_name() {
        assert_eq!(ApplicationsPlugin.name(), "applications");
    }

    #[test]
    fn test_applications_plugin_enabled_by_default() {
        assert!(ApplicationsPlugin.enabled_by_default());
    }
}
