// summarize command — matches Python's frais/commands/summarize.py.
use super::SummarizeArgs;
use std::collections::BTreeMap;

pub fn run(args: SummarizeArgs) -> Result<(), String> {
    // Load cached scan
    let mut scan_result = match crate::store::scan_cache::load_scan_cache(
        &crate::paths::advice_cache(),
    ) {
        Ok(sr) => sr,
        Err(e) => {
            super::output::exit_with_error(
                &format!("No scan cache found: {e}"),
                args.json,
                1,
                "no_cache",
                "Run `frais advise` or `frais scan` first to generate a scan cache.",
            BTreeMap::<String, serde_json::Value>::new(),
            );
        }
    };

    // Find candidate by item_id
    let mut found_candidate: Option<crate::models::UpdateCandidate> = None;
    for (_plugin_name, plugin_result) in &scan_result.plugin_results {
        for candidate in &plugin_result.candidates {
            if candidate.item.id == args.item_id {
                found_candidate = Some(candidate.clone());
                break;
            }
        }
        if found_candidate.is_some() {
            break;
        }
    }

    let mut candidate = match found_candidate {
        Some(c) => c,
        None => {
            super::output::exit_with_error(
                &format!("No candidate found for: {}", args.item_id),
                args.json,
                1,
                "candidate_not_found",
                "Run `frais scan --json` to see available candidate IDs.",
                {
                    let mut extra: BTreeMap<String, serde_json::Value> = BTreeMap::new();
                    extra.insert("item_id".into(), args.item_id.clone().into());
                    extra
                },
            );
        }
    };

    // If already summarized, return existing
    if let Some(ref summary) = candidate.ai_summary {
        if args.json {
            let mut extra: BTreeMap<String, serde_json::Value> = BTreeMap::new();
            extra.insert("item_id".into(), args.item_id.clone().into());
            extra.insert("ai_summary".into(), summary.clone().into());
            super::output::print_json_success(extra);
        } else {
            // Render markdown in terminal — matches Python's console.print(Markdown(summary))
            termimad::MadSkin::default().print_text(summary);
        }
        return Ok(());
    }

    // Get LLM client
    let config = match crate::store::config_store::load_config(
        &crate::paths::config_path(),
    ) {
        Some(c) if c.is_ready() => c,
        _ => {
            super::output::exit_with_error(
                "LLM not configured.",
                args.json,
                2,
                "config_missing",
                "Run `frais config manage` to configure an LLM provider.",
            BTreeMap::<String, serde_json::Value>::new(),
            );
        }
    };

    let llm = crate::llm::get_client(&config, None).map_err(|e| {
        format!("Cannot create LLM client: {e}")
    })?;

    // Find plugin for this candidate's item_id by scanning plugin_results
    let mut plugin_name: Option<String> = None;
    for (pname, plugin_result) in &scan_result.plugin_results {
        for c in &plugin_result.candidates {
            if c.item.id == args.item_id {
                plugin_name = Some(pname.clone());
                break;
            }
        }
        if plugin_name.is_some() {
            break;
        }
    }

    let plugin_name = plugin_name.unwrap_or_default();
    let all_plugins = crate::plugins::registry::all_plugins();
    let plugin = match all_plugins.get(&plugin_name) {
        Some(p) => p,
        None => {
            let mut extra: BTreeMap<String, serde_json::Value> = BTreeMap::new();
            extra.insert("item_id".into(), args.item_id.clone().into());
            extra.insert("plugin_name".into(), plugin_name.clone().into());
            super::output::exit_with_error(
                &format!("Plugin '{}' not found in registry", plugin_name),
                args.json,
                1,
                "plugin_not_found",
                "The plugin used to produce this candidate has been removed.",
                extra,
            );
        }
    };

    // Generate summary via plugin.summarize() — matches Python's flow
    if let Err(e) = plugin.summarize(&*llm, &mut candidate) {
        super::output::exit_with_error(
            &format!("LLM request failed: {e}"),
            args.json,
            1,
            "connection_error",
            "Check your API key and network connection.",
            BTreeMap::<String, serde_json::Value>::new(),
        );
    }

    let summary = candidate.ai_summary.clone().unwrap_or_default();

    // Update candidate in the in-memory scan result and save to cache
    if let Some(plugin_result) = scan_result.plugin_results.get_mut(&plugin_name) {
        for c in &mut plugin_result.candidates {
            if c.item.id == args.item_id {
                c.ai_summary = Some(summary.clone());
                break;
            }
        }
    }
    // Save updated cache atomically
    let _ = crate::store::scan_cache::save_scan_cache(
        &scan_result,
        &crate::paths::advice_cache(),
    );

    if args.json {
        let mut extra: BTreeMap<String, serde_json::Value> = BTreeMap::new();
        extra.insert("item_id".into(), args.item_id.clone().into());
        extra.insert("ai_summary".into(), summary.clone().into());
        super::output::print_json_success(extra);
    } else {
        // Render markdown in terminal — matches Python's console.print(Markdown(summary))
        termimad::MadSkin::default().print_text(&summary);
    }

    Ok(())
}
