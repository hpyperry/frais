// advise command — matches Python's frais/commands/advise.py.
use super::AdviseArgs;
use std::collections::BTreeMap;
use std::sync::Arc;
use std::time::Instant;

pub fn run(args: AdviseArgs) -> Result<(), String> {
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

    // Show unknown/disabled plugin warnings
    if !args.json {
        for w in &warnings {
            eprintln!("Warning: {w}");
        }
    }

    // Load config once for both DDGS warning and LLM summaries (avoid TOCTOU).
    let llm_config = crate::store::config_store::load_config(&crate::paths::config_path());

    // Warn before scan if web search will use DDGS fallback
    if !args.json {
        if let Some(ref c) = llm_config {
            if c.is_ready() {
                if let Ok(llm) = crate::llm::get_client(c, None) {
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

    // Store original handler for restoration on exit (matches Python's try/finally)
    let restore_handler = super::signal::install_interrupt_handler();

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

    // Build callbacks for coordinator::run_scan() — matches Python's
    // make_progress_callback + make_done_callback.
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
    let mut filtered_result = filter_result.scan_result;
    let ignored_count = filter_result.ignored_count;

    // --- LLM summaries with progress bar ---
    // Resolve language from config before moving llm_config into the client.
    let language = llm_config
        .as_ref()
        .map(|c| c.language.as_str())
        .unwrap_or("en");

    let llm: Option<Box<dyn crate::llm::base::LLMClient>> = match llm_config {
        Some(ref c) if c.is_ready() => crate::llm::get_client(c, None).ok(),
        _ => {
            if !args.json {
                eprintln!("Warning: LLM not configured. Skipping AI summaries.");
            }
            None
        }
    };

    let mut summarize_elapsed: f64 = 0.0;

    if let Some(ref agent) = llm {
        // Flatten candidates into a Vec for parallel summary processing.
        let mut all_cands: Vec<crate::models::UpdateCandidate> = Vec::new();
        let mut candidate_plugin_map: BTreeMap<usize, String> = BTreeMap::new();

        for (pname, pr) in &filtered_result.plugin_results {
            for c in &pr.candidates {
                all_cands.push(c.clone());
                candidate_plugin_map.insert(all_cands.len() - 1, pname.clone());
            }
        }

        let summary_count = all_cands.iter().filter(|c| c.ai_summary.is_none()).count();

        if summary_count > 0 {
            let summary_bar = if show_progress {
                Some(super::scan_progress::SummaryBar::new(summary_count))
            } else {
                None
            };

            // Run summaries in parallel via coordinator — matches Python's _run_summary_phase()
            let t0 = Instant::now();
            crate::coordinator::run_summaries(
                agent.as_ref(),
                &mut all_cands,
                &candidate_plugin_map,
                &all_plugins,
                args.jobs,
                Some(&|| {
                    if let Some(ref bar) = summary_bar {
                        bar.advance();
                    }
                }),
                language,
            );
            summarize_elapsed = t0.elapsed().as_secs_f64();

            if let Some(ref bar) = summary_bar {
                bar.finish();
            }

            // Write summaries back into filtered_result
            let mut idx: usize = 0;
            for pr in filtered_result.plugin_results.values_mut() {
                for c in &mut pr.candidates {
                    if idx < all_cands.len() && c.ai_summary.is_none() {
                        c.ai_summary = all_cands[idx].ai_summary.take();
                    }
                    idx += 1;
                }
            }
        }
    }

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
        print_results(
            &filtered_result,
            &all_plugins,
            &selected,
            ignored_count,
            args.all,
        );
    }

    // --- Total time (matches Python's _output_and_cache) ---
    if !args.json {
        let max_scan = scan_progress
            .as_ref()
            .map(|sp| sp.max_scan_time())
            .unwrap_or(0.0);
        let total = max_scan + summarize_elapsed;
        if total > 0.0 {
            eprintln!("  {}", super::output::dim(format!("Total: {:.1}s", total)));
        }
    }

    // --- Save cache ---
    match crate::store::scan_cache::save_scan_cache(&filtered_result, &crate::paths::advice_cache())
    {
        Ok(()) => {}
        Err(e) => log::warn!("failed to save advice cache: {}", e),
    }

    // Restore original SIGINT handler before returning
    restore_handler();

    Ok(())
}

/// Print scan results to stdout (shared by scan and advise commands).
/// Matches Python's _print_advise_result() in advise.py.
pub(crate) fn print_results(
    scan_result: &crate::models::ScanResult,
    all_plugins: &std::collections::BTreeMap<String, Box<dyn crate::plugins::ScannerPlugin>>,
    selected: &[String],
    ignored_count: usize,
    show_all: bool,
) {
    // Blank line before output — matches Python
    println!();

    // System header
    println!(
        "  {} {} {}  {} {}  {} {}",
        super::output::label("OS:"),
        scan_result.system.os_name,
        scan_result.system.os_version,
        super::output::label("Arch:"),
        scan_result.system.arch,
        super::output::label("Plugins:"),
        selected.join(", "),
    );
    println!();

    let terminal_width = console::Term::stdout().size().1 as usize;

    // Collect candidate IDs for --all up-to-date display
    let candidate_item_ids: std::collections::HashSet<_> = scan_result
        .all_candidates()
        .iter()
        .map(|c| c.item.id.clone())
        .collect();

    let mut any_output = false;

    // --all: show up-to-date items first (matches Python's _print_advise_result)
    if show_all {
        for name in selected {
            let result = match scan_result.plugin_results.get(name) {
                Some(r) => r,
                None => continue,
            };
            let current_items: Vec<_> = result
                .items
                .iter()
                .filter(|it| !candidate_item_ids.contains(&it.id))
                .collect();
            if current_items.is_empty() {
                continue;
            }
            any_output = true;
            let plugin_color = all_plugins
                .get(name)
                .map(|p| p.display_color())
                .unwrap_or("white");
            print_rule(name, current_items.len(), plugin_color, terminal_width, "up to date");
            for item in current_items {
                println!();
                println!("  {}", super::output::id(&item.id));
                let source_str = item.display_source();
                if item.name != item.id {
                    println!(
                        "  {}",
                        super::output::dim(format!("{} | {}", item.name, source_str))
                    );
                } else {
                    println!("  {}", super::output::dim(source_str));
                }
                let current = item.current_version.as_deref().unwrap_or("?");
                println!(
                    "  {}  {}",
                    super::output::bold(current),
                    super::output::dim("(up to date)")
                );
                println!();
            }
        }
    }

    // Show candidates (items with updates)
    for name in selected {
        let result = match scan_result.plugin_results.get(name) {
            Some(r) => r,
            None => continue,
        };

        if result.candidates.is_empty() {
            continue;
        }

        any_output = true;

        let plugin_color = all_plugins
            .get(name)
            .map(|p| p.display_color())
            .unwrap_or("white");
        print_rule(name, result.candidates.len(), plugin_color, terminal_width, "update(s)");

        for c in &result.candidates {
            println!();
            println!("  {}", super::output::id(&c.item.id));

            let source_str = c.item.display_source();
            if c.item.name != c.item.id {
                println!(
                    "  {}",
                    super::output::dim(format!("{} | {}", c.item.name, source_str))
                );
            } else {
                println!("  {}", super::output::dim(source_str));
            }

            let current = c.item.current_version.as_deref().unwrap_or("?");
            let latest = c.latest_version.as_deref().unwrap_or("?");
            println!(
                "  {} → {}",
                super::output::bold(current),
                super::output::green_bold(latest),
            );

            // AI summary — matches Python's Analysis section with rich.markdown.Markdown
            if let Some(ref summary) = c.ai_summary {
                println!();
                println!("  {}", super::output::dim("Analysis"));
                let skin = termimad::MadSkin::default();
                let indented = summary
                    .lines()
                    .map(|l| format!("  {}", l))
                    .collect::<Vec<_>>()
                    .join("\n");
                skin.print_text(&indented);
            }

            println!();
        }
    }

    if !any_output {
        println!("All software is up to date!");
    }

    if ignored_count > 0 {
        println!(
            "  {}",
            super::output::dim(format!(
                "{} app(s) ignored (use `frais ignore list` to review)",
                ignored_count
            ))
        );
    }
    println!();
}

/// Print a full-width horizontal rule with centered title in the plugin's color.
/// Matches Python's Rich Rule(f"[bold]{name}[/] — {count} {label}", style=color).
pub(crate) fn print_rule(name: &str, count: usize, color: &str, width: usize, label: &str) {
    use console::style;
    let title = format!(" {} — {} {} ", name, count, label);
    let width = if width == 0 { 80 } else { width };
    let dash_count = width.saturating_sub(title.len());
    let left = dash_count / 2;
    let right = dash_count - left;
    let line = format!("{}{}{}", "─".repeat(left), title, "─".repeat(right));
    let styled = match color {
        "cyan" => style(line).cyan(),
        "orange3" => style(line).yellow(),
        "bright_magenta" => style(line).magenta(),
        _ => style(line).white(),
    };
    println!("{styled}");
}
