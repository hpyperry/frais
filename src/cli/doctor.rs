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
        println!(
            "{} v{}",
            super::output::bold("Frais"),
            super::output::bold(env!("CARGO_PKG_VERSION"))
        );
        println!(
            "  {} {} {}",
            super::output::label("OS:"),
            system.os_name,
            system.os_version
        );
        println!("  {} {}", super::output::label("Arch:"), system.arch);
        println!();
        println!("{}", super::output::label("Plugins:"));
        for (_name, plugin) in &plugins {
            let status = if plugin.is_available() {
                super::output::check_mark()
            } else {
                super::output::cross_mark()
            };
            println!("  {} {}", status, plugin.name());
        }

        if let Some(c) = &config {
            let provider_name = crate::providers::get_provider(&c.provider)
                .map(|p| p.name)
                .unwrap_or_else(|| c.provider.clone());
            println!();
            println!(
                "{} {} {} ({})",
                super::output::label("LLM:"),
                provider_name,
                c.model,
                c.protocol
            );
            let lang_label = if c.language == "zh" { "中文" } else { "English" };
            println!("  {} {}", super::output::label("Language:"), lang_label);
            println!("  {} {}", super::output::label("Key:"), mask_key(&c.api_key));
        } else {
            println!();
            println!("{} {}", super::output::label("LLM:"), super::output::dim("not configured"));
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
