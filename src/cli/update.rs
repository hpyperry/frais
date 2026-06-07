// update command — matches Python's frais/commands/update.py.
use super::UpdateArgs;
use crate::models::UpdateCandidate;
use std::collections::BTreeMap;

pub fn run(args: UpdateArgs) -> Result<(), String> {
    // Load advice cache — matches Python's _load_advice_cache_or_exit()
    let cache_path = crate::paths::advice_cache();
    if !cache_path.exists() {
        println!("No advice cache found. Run `frais advise` first.");
        return Err("No advice cache found.".into());
    }

    let data: serde_json::Value = match std::fs::read_to_string(&cache_path) {
        Ok(content) => match serde_json::from_str(&content) {
            Ok(v) => v,
            Err(e) => {
                println!("Failed to read advice cache: {e}");
                return Err(format!("Failed to read advice cache: {e}"));
            }
        },
        Err(e) => {
            println!("Failed to read advice cache: {e}");
            return Err(format!("Failed to read advice cache: {e}"));
        }
    };

    // Parse candidates and build id→plugin_name map — matches _parse_candidates_from_cache()
    let (candidates, plugin_map) = parse_candidates_from_cache(&data);

    // Filter by exact id or name — matches _filter_candidates()
    let candidates = filter_candidates(&candidates, args.only.as_deref());
    if candidates.is_empty() {
        println!("No update candidates found.");
        return Ok(());
    }

    // Execute interactive update loop
    let plugins = crate::plugins::registry::all_plugins();
    execute_update_loop(&candidates, &plugin_map, &plugins);

    Ok(())
}

/// Parse UpdateCandidate list and build id→plugin_name map from cache.
/// Matches Python's _parse_candidates_from_cache().
fn parse_candidates_from_cache(
    data: &serde_json::Value,
) -> (Vec<UpdateCandidate>, BTreeMap<String, String>) {
    let mut plugin_map: BTreeMap<String, String> = BTreeMap::new();
    let mut candidates: Vec<UpdateCandidate> = Vec::new();

    let plugin_results = match data.get("plugin_results").and_then(|v| v.as_object()) {
        Some(pr) => pr,
        None => return (candidates, plugin_map),
    };

    for (plugin_name, pr) in plugin_results {
        let raw_candidates = match pr.get("candidates").and_then(|v| v.as_array()) {
            Some(arr) => arr,
            None => continue,
        };

        for raw_cand in raw_candidates {
            // Build plugin_map from item.id in each candidate
            if let Some(item) = raw_cand.get("item") {
                if let Some(item_id) = item.get("id").and_then(|v| v.as_str()) {
                    plugin_map.insert(item_id.to_string(), plugin_name.clone());
                }
            }

            // Parse UpdateCandidate from dict
            match serde_json::from_value::<UpdateCandidate>(raw_cand.clone()) {
                Ok(cand) => candidates.push(cand),
                Err(e) => {
                    log::warn!("failed to parse cached candidate: {}", e);
                }
            }
        }
    }

    (candidates, plugin_map)
}

/// Filter candidates by exact id or name match.
/// Matches Python's _filter_candidates() — EXACT match, not substring.
fn filter_candidates(
    candidates: &[UpdateCandidate],
    only: Option<&str>,
) -> Vec<UpdateCandidate> {
    match only {
        None => candidates.to_vec(),
        Some(filter) => candidates
            .iter()
            .filter(|c| c.item.id == filter || c.item.name == filter)
            .cloned()
            .collect(),
    }
}

/// Interactive confirmation loop: display, confirm, execute.
/// Matches Python's _execute_update_loop().
fn execute_update_loop(
    candidates: &[UpdateCandidate],
    plugin_map: &BTreeMap<String, String>,
    plugins: &BTreeMap<String, Box<dyn crate::plugins::ScannerPlugin>>,
) {
    for candidate in candidates {
        println!();
        println!(
            "  {}  ({})",
            candidate.item.name, candidate.item.id
        );
        println!(
            "  {} → {}",
            candidate.item.current_version.as_deref().unwrap_or("unknown"),
            candidate.latest_version.as_deref().unwrap_or("unknown"),
        );
        if let Some(ref summary) = candidate.ai_summary {
            println!();
            println!("  AI Analysis");
            // Render markdown in terminal — matches Python's console.print(Markdown(candidate.ai_summary))
            let skin = termimad::MadSkin::default();
            // Indent each line by 2 spaces to match Python's output
            let indented = summary
                .lines()
                .map(|l| format!("  {}", l))
                .collect::<Vec<_>>()
                .join("\n");
            skin.print_text(&indented);
        } else {
            println!();
            println!(
                "  No AI summary yet — `frais summarize {}`",
                candidate.item.id
            );
        }

        if candidate.can_auto_update
            && candidate.item.source != crate::models::SourceKind::AppStore
        {
            println!("    cmd: {}", candidate.command.join(" "));
        } else if !candidate.can_auto_update {
            println!("    manual update");
        }

        // Confirm — matches typer.confirm("  Proceed?", default=False)
        print!("  Proceed? [y/N]: ");
        use std::io::Write;
        let _ = std::io::stdout().flush();
        let mut input = String::new();
        std::io::stdin().read_line(&mut input).ok();
        if input.trim().to_lowercase() != "y" {
            log::info!("update skipped name={}", candidate.item.name);
            continue;
        }

        // Look up plugin from cache-built map — matches Python's plugin_map.get(candidate.item.id)
        let plugin_name = plugin_map.get(&candidate.item.id);
        let plugin = plugin_name.and_then(|n| plugins.get(n));
        if let Some(plugin) = plugin {
            let ok = plugin.update(candidate);
            log::info!(
                "update executed plugin={} name={} ok={}",
                plugin_name.unwrap_or(&String::new()),
                candidate.item.name,
                ok
            );
        } else {
            log::warn!(
                "update skipped: no plugin found for candidate {} (plugin_name={:?}, plugin_map keys={:?})",
                candidate.item.id,
                plugin_name,
                plugin_map.keys().collect::<Vec<_>>()
            );
            eprintln!("  Warning: no plugin found for {} — the cache may be corrupt. Try running `frais advise` again.", candidate.item.id);
        }
    }

    println!();
}
