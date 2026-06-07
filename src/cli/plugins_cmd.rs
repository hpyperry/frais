// plugins commands — matches Python's frais/commands/plugins.py.
use super::{JsonFlag, PluginAction};
use std::collections::BTreeMap;

pub fn list(args: JsonFlag) -> Result<(), String> {
    let plugins = crate::plugins::registry::all_plugins();
    let persisted =
        crate::store::plugin_store::load_plugins_config(&crate::paths::plugins_config_path());

    if args.json() {
        let mut list = Vec::new();
        for (name, plugin) in &plugins {
            let effective = persisted
                .get(name)
                .copied()
                .unwrap_or_else(|| plugin.enabled_by_default());
            let mut entry: BTreeMap<String, serde_json::Value> = BTreeMap::new();
            entry.insert("name".into(), name.clone().into());
            entry.insert(
                "available".into(),
                if plugin.is_available() { "yes" } else { "no" }.into(),
            );
            entry.insert(
                "default".into(),
                if plugin.enabled_by_default() {
                    "enabled"
                } else {
                    "disabled"
                }
                .into(),
            );
            entry.insert(
                "effective".into(),
                if effective { "enabled" } else { "disabled" }.into(),
            );
            list.push(serde_json::json!(entry));
        }
        let mut extra: BTreeMap<String, serde_json::Value> = BTreeMap::new();
        extra.insert("plugins".into(), serde_json::json!(list));
        super::output::print_json_success(extra);
    } else {
        for (name, plugin) in &plugins {
            let effective = persisted
                .get(name)
                .copied()
                .unwrap_or_else(|| plugin.enabled_by_default());
            let status = if plugin.is_available() {
                super::output::check_mark()
            } else {
                super::output::cross_mark()
            };
            let state = if effective {
                super::output::success("enabled")
            } else {
                super::output::dim("disabled")
            };
            println!("  {} {:<20} {}", status, name, state);
        }
    }
    Ok(())
}

pub fn enable(args: PluginAction) -> Result<(), String> {
    let plugins = crate::plugins::registry::all_plugins();
    if !plugins.contains_key(&args.name) {
        let mut extra: BTreeMap<String, serde_json::Value> = BTreeMap::new();
        extra.insert("plugin_name".into(), args.name.clone().into());
        super::output::exit_with_error(
            &format!("Unknown plugin: {}", args.name),
            args.json,
            1,
            "unknown_plugin",
            "Run `frais plugins list --json` to see available plugins.",
            extra,
        );
    }

    crate::store::plugin_store::save_plugin_state(
        &args.name,
        true,
        &crate::paths::plugins_config_path(),
    )
    .map_err(|e| format!("Cannot save plugin state: {e}"))?;

    if args.json {
        let mut extra: BTreeMap<String, serde_json::Value> = BTreeMap::new();
        extra.insert("plugin".into(), args.name.clone().into());
        extra.insert("action".into(), "enabled".into());
        super::output::print_json_success(extra);
    } else {
        println!(
            "{}",
            super::output::success(format!("Plugin '{}' enabled.", args.name))
        );
    }
    Ok(())
}

pub fn disable(args: PluginAction) -> Result<(), String> {
    let plugins = crate::plugins::registry::all_plugins();
    if !plugins.contains_key(&args.name) {
        let mut extra: BTreeMap<String, serde_json::Value> = BTreeMap::new();
        extra.insert("plugin_name".into(), args.name.clone().into());
        super::output::exit_with_error(
            &format!("Unknown plugin: {}", args.name),
            args.json,
            1,
            "unknown_plugin",
            "Run `frais plugins list --json` to see available plugins.",
            extra,
        );
    }

    crate::store::plugin_store::save_plugin_state(
        &args.name,
        false,
        &crate::paths::plugins_config_path(),
    )
    .map_err(|e| format!("Cannot save plugin state: {e}"))?;

    if args.json {
        let mut extra: BTreeMap<String, serde_json::Value> = BTreeMap::new();
        extra.insert("plugin".into(), args.name.clone().into());
        extra.insert("action".into(), "disabled".into());
        super::output::print_json_success(extra);
    } else {
        println!(
            "{}",
            super::output::dim(format!("Plugin '{}' disabled.", args.name))
        );
    }
    Ok(())
}
