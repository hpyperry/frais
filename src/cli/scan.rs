// scan command — matches Python's frais/commands/scan.py.
use super::ScanArgs;
use std::collections::BTreeMap;
use std::sync::Arc;

pub fn run(args: ScanArgs) -> Result<(), String> {
    // Install SIGINT handler for cursor restoration on Ctrl+C during progress bars.
    let _restore_handler = super::signal::install_interrupt_handler();

    let system = crate::system::detect_system();
    let all_plugins = crate::plugins::registry::all_plugins();

    // --- Resolve plugins via coordinator (respects persisted state) ---
    let (selected, warnings) =
        crate::coordinator::select_plugins(args.plugins.as_deref(), &all_plugins);

    if selected.is_empty() {
        let unknown: Vec<&String> = warnings
            .iter()
            .filter(|w| w.starts_with("Unknown plugin: "))
            .collect();
        let detail = if !unknown.is_empty() {
            let names: Vec<String> = unknown
                .iter()
                .map(|w| w.trim_start_matches("Unknown plugin: ").to_string())
                .collect();
            format!("No available plugins matched: {}", names.join(", "))
        } else if !warnings.is_empty() {
            warnings.join("; ")
        } else {
            "No plugins available or enabled.".into()
        };
        let mut extra: BTreeMap<String, serde_json::Value> = BTreeMap::new();
        if let Some(ref requested) = args.plugins {
            extra.insert(
                "requested".into(),
                serde_json::Value::Array(requested.iter().map(|s| s.clone().into()).collect()),
            );
        }
        super::output::exit_with_error(
            &detail,
            args.json,
            1,
            "no_plugins_matched",
            "Run `frais plugins list --json` to see available plugins.",
            extra,
        );
    }

    if !args.json {
        for w in &warnings {
            eprintln!("Warning: {w}");
        }
    }

    // Warn if the LLM client doesn't support server-side web search (DDGS fallback)
    if !args.json {
        if let Some(c) = crate::store::config_store::load_config(&crate::paths::config_path()) {
            if c.is_ready() {
                if let Ok(llm) = crate::llm::get_client(&c, None) {
                    if !llm.supports_web_search() {
                        use console::style;
                        eprintln!(
                            "  {}",
                            style(
                                "Note: web search uses DuckDuckGo fallback (less accurate). \
                                 Switch to a provider/client with server-side search for best results."
                            )
                            .dim()
                        );
                    }
                }
            }
        }
    }

    // --- Scan phase with live progress bars ---
    let show_progress = !args.json;
    let scan_progress: Option<Arc<super::scan_progress::ScanProgress>> = if show_progress {
        Some(super::scan_progress::ScanProgress::new(
            &selected,
            &all_plugins,
        ))
    } else {
        None
    };

    // Build callbacks for coordinator::run_scan()
    #[allow(clippy::type_complexity)]
    let on_plugin_progress: Option<Box<dyn Fn(&str, usize, usize, usize) + Send + Sync>> =
        scan_progress.as_ref().map(|sp| {
            let sp = Arc::clone(sp);
            Box::new(move |name: &str, step: usize, done: usize, total: usize| {
                sp.update(name, step, done, total);
            }) as Box<dyn Fn(&str, usize, usize, usize) + Send + Sync>
        });

    #[allow(clippy::type_complexity)]
    let on_plugin_done: Option<
        Box<dyn Fn(&str, &crate::models::PluginScanResult) + Send + Sync>,
    > = scan_progress.as_ref().map(|sp| {
        let sp = Arc::clone(sp);
        Box::new(
            move |name: &str, result: &crate::models::PluginScanResult| {
                sp.finish(name, result.items.len(), result.candidates.len());
            },
        ) as Box<dyn Fn(&str, &crate::models::PluginScanResult) + Send + Sync>
    });

    // Parallel plugin scanning — matches Python's run_scan_phase → coordinator.run_scan
    let scan_result = crate::coordinator::run_scan(
        &selected,
        &all_plugins,
        &system,
        args.all,
        args.jobs,
        on_plugin_progress.as_deref(),
        on_plugin_done.as_deref(),
    );

    // --- Apply ignore filter ---
    let filter_result = crate::ignore_filter::apply_ignore_filter(&scan_result);
    let filtered_result = filter_result.scan_result;
    let ignored_count = filter_result.ignored_count;

    // --- Output ---
    if args.json {
        let mut extra: BTreeMap<String, serde_json::Value> = BTreeMap::new();
        extra.insert(
            "system".into(),
            serde_json::to_value(&filtered_result.system).unwrap_or_default(),
        );
        extra.insert(
            "plugin_results".into(),
            serde_json::to_value(&filtered_result.plugin_results).unwrap_or_default(),
        );
        super::output::print_json_success(extra);
    } else {
        super::advise::print_results(
            &filtered_result,
            &all_plugins,
            &selected,
            ignored_count,
            args.all,
        );

        // Total time
        let total = scan_progress
            .as_ref()
            .map(|sp| sp.max_scan_time())
            .unwrap_or(0.0);
        if total > 0.0 {
            eprintln!("  {}", super::output::dim(format!("Total: {:.1}s", total)));
        }
    }

    // --- Save cache ---
    match crate::store::scan_cache::save_scan_cache(&filtered_result, &crate::paths::advice_cache())
    {
        Ok(()) => {}
        Err(e) => log::warn!("failed to save scan cache: {}", e),
    }

    Ok(())
}
