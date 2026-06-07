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
        let mut sys: BTreeMap<String, serde_json::Value> = BTreeMap::new();
        sys.insert("os_name".into(), serde_json::Value::String(system.os_name.clone()));
        sys.insert("os_version".into(), serde_json::Value::String(system.os_version.clone()));
        sys.insert("arch".into(), serde_json::Value::String(system.arch.clone()));
        extra.insert("system".into(), serde_json::json!(sys));

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
            llm.insert("language".into(), c.language.clone().into());
            llm.insert("key_suffix".into(), mask_key(&c.api_key).into());
            extra.insert("llm".into(), serde_json::json!(llm));
        } else {
            extra.insert("llm".into(), serde_json::Value::Null);
        }

        super::output::print_json_success(extra);
    } else {
        // Header
        println!(
            "{} v{}",
            super::output::bold("frais"),
            super::output::bold(env!("CARGO_PKG_VERSION"))
        );
        println!();

        // --- System ---
        println!("{}", super::output::section_header("System"));
        super::output::info_row("OS", &format!("{} {}", system.os_name, super::output::dim(&system.os_version)));
        super::output::info_row("Arch", &system.arch);
        println!();

        // --- Plugins ---
        println!("{}", super::output::section_header("Plugins"));
        for plugin in plugins.values() {
            let name = plugin.name();
            let display = match name {
                "applications" => "Applications",
                "homebrew" => "Homebrew",
                "npm" => "NPM",
                other => other,
            };
            if plugin.is_available() {
                println!("  {}  {}", super::output::check_mark(), display);
            } else {
                println!("  {}  {}", super::output::cross_mark(), display);
            }
        }
        println!();

        // --- LLM ---
        if let Some(c) = &config {
            println!("{}", super::output::section_header("LLM"));
            let provider_name = crate::providers::get_provider(&c.provider)
                .map(|p| p.name)
                .unwrap_or_else(|| c.provider.clone());
            super::output::info_row("Provider", &provider_name);
            super::output::info_row("Model", &c.model);
            let protocol_display = match c.protocol.as_str() {
                "openai" => "OpenAI",
                "anthropic" => "Anthropic",
                other => other,
            };
            super::output::info_row("Protocol", protocol_display);
            let endpoint = if c.url.is_empty() {
                "(default)".to_string()
            } else {
                c.url
                    .trim_start_matches("https://")
                    .trim_start_matches("http://")
                    .trim_end_matches('/')
                    .to_string()
            };
            super::output::info_row("Endpoint", &endpoint);
            let lang_label = if c.language == "zh" { "中文" } else { "English" };
            super::output::info_row("Language", lang_label);
            super::output::info_row_dim("Key", &format!("{}  ({})", mask_key(&c.api_key), key_source_label(c.api_key_source.as_deref())));
        } else {
            println!("{}", super::output::section_header("LLM"));
            println!("  {}", super::output::dim("Not configured. Run `frais config manage` to set up."));
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

fn key_source_label(source: Option<&str>) -> &str {
    match source {
        Some("FRAIS_LLM_API_KEY") | Some("MIMO_API_KEY") | Some("OPENAI_API_KEY") => "env var",
        Some(s) if s.ends_with("config.toml") => "config file",
        _ => "unknown",
    }
}
