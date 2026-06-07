// advise command — matches Python's frais/commands/advise.py.
use super::AdviseArgs;
use std::collections::BTreeMap;
use std::sync::Arc;
use std::time::Instant;

pub fn run(args: AdviseArgs) -> Result<(), String> {
    let system = crate::system::detect_system();
    let all_plugins = crate::plugins::registry::all_plugins();

    // --- Resolve plugins via coordinator (respects persisted state) ---
    let (selected, warnings) = crate::coordinator::select_plugins(
        args.plugins.as_deref(),
        &all_plugins,
    );

    if selected.is_empty() {
        let unknown: Vec<&String> = warnings.iter()
            .filter(|w| w.starts_with("Unknown plugin: "))
            .collect();
        let detail = if !unknown.is_empty() {
            let names: Vec<String> = unknown.iter()
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

    // Warn before scan if web search will use DDGS fallback
    if !args.json {
        if let Some(ref c) = crate::store::config_store::load_config(&crate::paths::config_path()) {
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
        Some(super::scan_progress::ScanProgress::new(&selected, &all_plugins))
    } else {
        None
    };

    // Build callbacks for coordinator::run_scan() — matches Python's
    // make_progress_callback + make_done_callback.
    let on_plugin_progress: Option<Box<dyn Fn(&str, usize, usize, usize) + Send + Sync>> =
        scan_progress.as_ref().map(|sp| {
            let sp = Arc::clone(sp);
            Box::new(move |name: &str, step: usize, done: usize, total: usize| {
                sp.update(name, step, done, total);
            }) as Box<dyn Fn(&str, usize, usize, usize) + Send + Sync>
        });

    let on_plugin_done: Option<Box<dyn Fn(&str, &crate::models::PluginScanResult) + Send + Sync>> =
        scan_progress.as_ref().map(|sp| {
            let sp = Arc::clone(sp);
            Box::new(move |name: &str, result: &crate::models::PluginScanResult| {
                sp.finish(name, result.items.len(), result.candidates.len());
            }) as Box<dyn Fn(&str, &crate::models::PluginScanResult) + Send + Sync>
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
    let llm_config = crate::store::config_store::load_config(&crate::paths::config_path());
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
            );
            summarize_elapsed = t0.elapsed().as_secs_f64();

            if let Some(ref bar) = summary_bar {
                bar.finish();
            }

            // Write summaries back into filtered_result
            let mut idx: usize = 0;
            for (_pname, pr) in &mut filtered_result.plugin_results {
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
        // Blank line before output — matches Python
        println!();

        // System header — matches Python's _print_advise_header()
        // "[bold cyan]OS:[/] macOS 14.5  [bold cyan]Arch:[/] arm64  [bold cyan]Plugins:[/] ..."
        println!(
            "  {} {} {}  {} {}  {} {}",
            super::output::label("OS:"),
            filtered_result.system.os_name,
            filtered_result.system.os_version,
            super::output::label("Arch:"),
            filtered_result.system.arch,
            super::output::label("Plugins:"),
            selected.join(", "),
        );
        println!();

        // --- Results per plugin ---
        // Matches Python's _print_advise_result() exactly.
        let terminal_width = console::Term::stdout().size().1 as usize;

        let mut any_candidates = false;
        for name in &selected {
            let result = match filtered_result.plugin_results.get(name) {
                Some(r) => r,
                None => continue,
            };

            if result.candidates.is_empty() {
                continue;
            }

            any_candidates = true;
            let candidates = &result.candidates;

            // Plugin section separator — matches Python's Rule(f"[bold]{pname}[/] — {len} update(s)", style=color)
            let plugin_color = all_plugins
                .get(name)
                .map(|p| p.display_color())
                .unwrap_or("white");
            print_rule(name, candidates.len(), plugin_color, terminal_width);

            for c in candidates {
                println!();
                // Item ID — bold white, 2-space indent
                println!("  {}", super::output::id(&c.item.id));

                // Name | source — dim, 2-space indent
                let source_str = c.item.source.as_str();
                if c.item.name != c.item.id {
                    println!(
                        "  {}",
                        super::output::dim(&format!("{} | {}", c.item.name, source_str))
                    );
                } else {
                    println!("  {}", super::output::dim(source_str));
                }

                // Version — [bold]current[/] → [bold green]latest[/]
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
                    // Render markdown in terminal — matches Python's console.print(Markdown(summary))
                    let skin = termimad::MadSkin::default();
                    // Indent each line by 2 spaces to match Python's output
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

        if !any_candidates {
            println!("All software is up to date!");
        }

        if ignored_count > 0 {
            println!(
                "  {}",
                super::output::dim(&format!(
                    "{} app(s) ignored (use `frais ignore list` to review)",
                    ignored_count
                ))
            );
        }
        println!();
    }

    // --- Total time (matches Python's _output_and_cache) ---
    if !args.json {
        let max_scan = scan_progress
            .as_ref()
            .map(|sp| sp.max_scan_time())
            .unwrap_or(0.0);
        let total = max_scan + summarize_elapsed;
        if total > 0.0 {
            eprintln!("  {}", super::output::dim(&format!("Total: {:.1}s", total)));
        }
    }

    // --- Save cache ---
    match crate::store::scan_cache::save_scan_cache(
        &filtered_result,
        &crate::paths::advice_cache(),
    ) {
        Ok(()) => {}
        Err(e) => log::warn!("failed to save advice cache: {}", e),
    }

    // Restore original SIGINT handler before returning
    restore_handler();

    Ok(())
}

/// Print a full-width horizontal rule with centered title in the plugin's color.
/// Matches Python's Rich Rule(f"[bold]{name}[/] — {count} update(s)", style=color).
pub(crate) fn print_rule(name: &str, count: usize, color: &str, width: usize) {
    use console::style;
    let title = format!(" {} — {} update(s) ", name, count);
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
