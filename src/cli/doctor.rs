// doctor command — matches Python's frais/commands/doctor.py.
use super::DoctorArgs;
use std::collections::BTreeMap;

pub fn run(args: DoctorArgs) -> Result<(), String> {
    let system = crate::system::detect_system();
    let plugins = crate::plugins::registry::all_plugins();
    let config = crate::store::config_store::load_config(&crate::paths::config_path());

    if args.json {
        let mut extra: BTreeMap<String, serde_json::Value> = BTreeMap::new();
        extra.insert("version".into(), serde_json::Value::String(env!("CARGO_PKG_VERSION").into()));
        extra.insert("system".into(), serde_json::to_value(&system).unwrap_or_default());

        // Plugins status
        let mut plugin_info: BTreeMap<String, serde_json::Value> = BTreeMap::new();
        for (name, plugin) in &plugins {
            let mut info: BTreeMap<String, serde_json::Value> = BTreeMap::new();
            info.insert("available".into(), if plugin.is_available() { "yes" } else { "no" }.into());
            info.insert("default".into(), if plugin.enabled_by_default() { "enabled" } else { "disabled" }.into());
            plugin_info.insert(name.clone(), serde_json::json!(info));
        }
        extra.insert("plugins".into(), serde_json::json!(plugin_info));

        // LLM config
        if let Some(c) = &config {
            // Resolve provider display name from provider ID
            let provider_name = crate::providers::get_provider(&c.provider)
                .map(|p| p.name)
                .unwrap_or_else(|| c.provider.clone());

            let mut llm: BTreeMap<String, serde_json::Value> = BTreeMap::new();
            llm.insert("configured".into(), serde_json::Value::Bool(c.is_ready()));
            llm.insert("provider".into(), provider_name.into());
            llm.insert("model".into(), c.model.clone().into());
            llm.insert("protocol".into(), c.protocol.clone().into());
            llm.insert("url".into(), c.url.clone().into());
            llm.insert("key_suffix".into(), mask_key(&c.api_key).into());
            extra.insert("llm".into(), serde_json::json!(llm));
        } else {
            extra.insert("llm".into(), serde_json::Value::Null);
        }

        super::output::print_json_success(extra);
    } else {
        println!("Frais v{}", env!("CARGO_PKG_VERSION"));
        println!("  OS:      {} {}", system.os_name, system.os_version);
        println!("  Arch:    {}", system.arch);
        println!("  Apps:    {}", system.applications_paths.join(", "));
        println!();
        println!("Plugins:");
        for (_name, plugin) in &plugins {
            let status = if plugin.is_available() { "✓" } else { "✗" };
            println!("  {} {}", status, plugin.name());
        }

        if let Some(c) = &config {
            let provider_name = crate::providers::get_provider(&c.provider)
                .map(|p| p.name)
                .unwrap_or_else(|| c.provider.clone());
            println!("\nLLM: {} / {} ({})", provider_name, c.model, c.protocol);
            println!("  Key: {}", mask_key(&c.api_key));
        } else {
            println!("\nLLM: not configured");
        }
    }

    Ok(())
}

fn mask_key(key: &str) -> String {
    if key.len() <= 4 {
        "***".into()
    } else {
        format!("***{}", &key[key.len() - 4..])
    }
}
